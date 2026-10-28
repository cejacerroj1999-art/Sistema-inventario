from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from streamlit.testing.v1 import AppTest


class FakeDB:
    """Sólo simula transporte: las reglas SQL se verifican en 004_pruebas_acceso.sql."""
    def __init__(self):
        self.valid = False
        self.actor = dict(id='11111111-1111-4111-8111-111111111111',usuario='Administrador',
                          login='hector.admin',rol='administrador',activo=True)
    def rpc(self, name, args):
        if name == 'iniciar_sesion_local':
            self.valid = args == dict(p_login='hector.admin',p_password='UnaClaveLarga123!')
            result = dict(token='a'*64,usuario_id=self.actor['id']) if self.valid else None
        elif name == 'validar_sesion_local':
            result = self.actor if self.valid and args['p_token']=='a'*64 else None
        elif name == 'cerrar_sesion_local':
            self.valid = False
            result = None
        else:
            raise AssertionError(name)
        return SimpleNamespace(execute=lambda:SimpleNamespace(data=result))


def app():
    at=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'))
    at.secrets['SUPABASE_URL']='https://example.supabase.co'
    at.secrets['SUPABASE_SERVICE_KEY']='fake-only-for-test'
    at.secrets['COOKIE_SECURE']=False
    return at


def test_login_form_and_logout_with_server_session():
    fake=FakeDB()
    with patch('supabase.create_client',return_value=fake):
        at=app().run()
        assert not at.exception
        assert [x.label for x in at.text_input]==['Usuario','Contraseña']
        at.text_input[0].set_value('hector.admin')
        at.text_input[1].set_value('UnaClaveLarga123!')
        at.button[0].click().run()
        assert not at.exception
        next(b for b in at.button if b.label=='Entrar al inventario').click().run()
        assert not at.exception
        assert any(b.label=='Cerrar sesión' for b in at.button)
        next(b for b in at.button if b.label=='Cerrar sesión').click().run()
        assert not at.exception
        assert not fake.valid
        assert [x.label for x in at.text_input]==['Usuario','Contraseña']


def test_bad_credentials_do_not_show_inventory():
    with patch('supabase.create_client',return_value=FakeDB()):
        at=app().run()
        at.text_input[0].set_value('hector.admin')
        at.text_input[1].set_value('incorrecta')
        at.button[0].click().run()
        assert not at.exception
        assert any('No se pudo iniciar sesión' in e.value for e in at.error)
        assert not any(b.label=='Cerrar sesión' for b in at.button)
