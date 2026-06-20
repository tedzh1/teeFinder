import datetime as dt

import pytest

from teefinder.accounts import DuplicateEmailError, UserStore
from teefinder.config import UserConfig


def _store(tmp_path):
    return UserStore(tmp_path / "tf.db")


def test_create_and_authenticate(tmp_path):
    store = _store(tmp_path)
    user = store.create_user("Ted@Example.com", "s3cret-pass", "Ted")
    assert isinstance(user, UserConfig)
    assert user.email == "ted@example.com"  # normalised to lowercase
    assert user.name == "Ted"
    assert user.min_players == 1  # default
    assert user.clubs == []       # default -> all clubs

    assert store.authenticate("ted@example.com", "s3cret-pass") is not None
    assert store.authenticate("ted@example.com", "wrong") is None
    assert store.authenticate("nobody@example.com", "s3cret-pass") is None


def test_duplicate_email_rejected(tmp_path):
    store = _store(tmp_path)
    store.create_user("a@b.com", "pw12345678", "A")
    with pytest.raises(DuplicateEmailError):
        store.create_user("A@B.com", "another-pw", "A2")  # case-insensitive dupe


def test_password_is_hashed_not_plaintext(tmp_path):
    store = _store(tmp_path)
    store.create_user("a@b.com", "pw12345678", "A")
    row = store.get_row_by_email("a@b.com")
    assert row["password_hash"] != "pw12345678"
    assert row["password_hash"].startswith("$2")  # bcrypt prefix


def test_update_profile_validates_and_persists(tmp_path):
    store = _store(tmp_path)
    user = store.create_user("a@b.com", "pw12345678", "Alex")
    uid = store.id_for_email("a@b.com")

    updated = store.update_profile(
        uid,
        name="Alex G",
        min_players=2,
        clubs=["wakehurst", "demo"],
        preferences=[
            {"days": ["Saturday", "Sunday"], "time_ranges": [{"start": "06:00", "end": "10:00"}]}
        ],
    )
    assert updated.name == "Alex G"
    assert updated.min_players == 2
    assert updated.clubs == ["wakehurst", "demo"]
    # Saturday=5, Sunday=6 — parsed via the shared config validators.
    assert updated.preferences[0].days == [5, 6]
    assert updated.preferences[0].time_ranges[0].start == dt.time(6, 0)

    # Reloading from a fresh store proves it persisted.
    reloaded = UserStore(tmp_path / "tf.db").get_by_email("a@b.com")
    assert reloaded.clubs == ["wakehurst", "demo"]
    assert reloaded.preferences[0].days == [5, 6]


def test_update_profile_rejects_invalid_input(tmp_path):
    store = _store(tmp_path)
    store.create_user("a@b.com", "pw12345678", "A")
    uid = store.id_for_email("a@b.com")
    with pytest.raises(Exception):
        store.update_profile(uid, name="A", min_players=9, clubs=[], preferences=[])  # min_players>4
    with pytest.raises(Exception):
        store.update_profile(
            uid, name="A", min_players=1, clubs=[],
            preferences=[{"days": ["Funday"], "time_ranges": []}],
        )


def test_list_active_returns_userconfigs(tmp_path):
    store = _store(tmp_path)
    store.create_user("a@b.com", "pw12345678", "A")
    store.create_user("c@d.com", "pw12345678", "C")
    users = store.list_active()
    assert {u.email for u in users} == {"a@b.com", "c@d.com"}
    assert all(isinstance(u, UserConfig) for u in users)
