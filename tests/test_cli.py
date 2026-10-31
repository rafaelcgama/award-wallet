import stat

import pytest

from award_wallet.cli import main
from award_wallet.config import Settings
from award_wallet.security.vault import Vault


def test_init_writes_private_working_keys(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    main(["init"])

    env_file = tmp_path / ".env"
    assert stat.S_IMODE(env_file.stat().st_mode) == 0o600
    settings = Settings(_env_file=env_file)
    vault = Vault.from_config(settings.encryption_keys.get_secret_value())
    assert vault.decrypt(vault.encrypt(b"ok", context="c"), context="c") == b"ok"


def test_init_never_overwrites_existing_keys(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("AW_SECRET_KEY=keep-me\n")
    with pytest.raises(SystemExit):
        main(["init"])
    assert (tmp_path / ".env").read_text() == "AW_SECRET_KEY=keep-me\n"
