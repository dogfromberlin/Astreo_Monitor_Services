"""Copie dei backup con rclone, provate su destinazioni locali (rclone tratta i percorsi assoluti come una destinazione)."""
import os
import shutil

import pytest

from astreo_monitor import rclone

pytestmark = pytest.mark.skipif(not shutil.which("rclone"), reason="rclone non installato")


@pytest.mark.parametrize("dest", ["ftp://nas/backup", "nas", "../evasione", "/tmp/../etc"])
def test_destinazioni_non_valide(dest):
    with pytest.raises(rclone.RcloneError):
        rclone.validate(dest)


def test_parse():
    assert rclone.parse("nas:backup/\n /mnt/disco ,b2:secchio") == ["nas:backup", "/mnt/disco", "b2:secchio"]


def test_copia_verifica_e_pulizia(tmp_path):
    dest = str(tmp_path / "copie")
    assert "0 backup" in rclone.test(dest)
    for i in range(4):
        d = tmp_path / "locali" / f"backup-2026110{i + 1}-020000"
        d.mkdir(parents=True)
        (d / "db.zst").write_bytes(os.urandom(1000 + i))
        (d / "SHA256SUMS").write_text("x")
        assert rclone.upload(str(d), dest, 60).endswith(d.name)
    assert rclone.prune(dest, 2) == ["backup-20261101-020000", "backup-20261102-020000"]
    assert sorted(os.listdir(dest)) == ["backup-20261103-020000", "backup-20261104-020000"]
    assert os.path.getsize(os.path.join(dest, "backup-20261104-020000", "db.zst")) == 1003


def test_remote_inesistente():
    with pytest.raises(rclone.RcloneError) as exc:
        rclone.test("remoteinesistente:cartella")
    assert not str(exc.value).startswith("20")            # niente data e ora di rclone nel messaggio
