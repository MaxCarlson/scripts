import pytest
from edit_commands.core import apply_vim_substitution

def test_vim_substitution():
    assert apply_vim_substitution("echo test", "s/test/success/g") == "echo success"
