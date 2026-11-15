from streetfill import __version__
from streetfill.cli import main


def test_help_runs(capsys):
    assert main([]) == 0
    assert "streetfill" in capsys.readouterr().out


def test_version():
    assert __version__ == "0.1.0"
