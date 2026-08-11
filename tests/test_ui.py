import pytest
import time
try:
    import tkinter as tk
    from linux_barcode_app import BarcodeApp, tk as tk_module
except Exception:
    tk = None

pytestmark = pytest.mark.skipif(tk is None, reason="tkinter not available")


def setup_app():
    root = tk.Tk()
    root.withdraw()
    app = BarcodeApp()
    app.update()
    return app, root


def teardown_app(app, root):
    try:
        app.destroy()
    except Exception:
        pass
    try:
        root.destroy()
    except Exception:
        pass


def test_jurisdiction_lock_toggle():
    app, root = setup_app()
    try:
        # lock it
        app._set_jurisdiction_editable(False)
        btn = getattr(app, 'jurisdiction_lock_button', None)
        assert btn is not None
        assert app.jurisdiction_locked is True
        assert btn.cget('text') == 'Unlock'

        # toggle to unlock
        app._toggle_jurisdiction_lock()
        app.update()
        assert app.jurisdiction_locked is False
        assert btn.cget('text') == 'Lock'
    finally:
        teardown_app(app, root)


def test_hair_visibility_on_state_change():
    app, root = setup_app()
    try:
        hair_widget = app.fields.get('hair_color')
        assert hair_widget is not None
        # set state to something that hides hair
        state_var = app.fields['state_code'].variable
        state_var.set('')
        app.on_state_code_changed(state_var)
        app.update()
        assert not hair_widget.winfo_ismapped()

        # set state to CA which should show hair
        state_var.set('CA')
        app.on_state_code_changed(state_var)
        app.update()
        assert hair_widget.winfo_ismapped()
    finally:
        teardown_app(app, root)
