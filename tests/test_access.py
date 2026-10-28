import bcrypt
import pytest
from access import hash_password, valid_login


def test_password_hash_is_salted_and_accepts_only_correct_password():
    one = hash_password('UnaClaveLarga123!')
    two = hash_password('UnaClaveLarga123!')
    assert one != two
    assert bcrypt.checkpw(b'UnaClaveLarga123!',one.encode())
    assert not bcrypt.checkpw(b'Incorrecta123!',one.encode())


@pytest.mark.parametrize('value',['corta', 'á'*37, 'x'*73])
def test_password_policy_prevents_short_passwords_and_bcrypt_truncation(value):
    with pytest.raises(ValueError):
        hash_password(value)


def test_username_policy():
    assert valid_login('hector.admin')
    assert valid_login('vendedor_01')
    for bad in ('HeCtor','con espacio','ab','<script>','ábc'):
        assert not valid_login(bad)
