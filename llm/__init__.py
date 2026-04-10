# Odoo 14: el core no define fields.Json (existe desde versiones posteriores).
import odoo.fields as _odoo_fields

from . import fields_json

if not hasattr(_odoo_fields, "Json"):
    _odoo_fields.Json = fields_json.Json

# ir.model.fields se inicializó antes con FIELD_TYPES sin 'json'; actualizar selección.
try:
    import odoo.addons.base.models.ir_model as _ir_model

    _ir_model.FIELD_TYPES = [
        (key, key) for key in sorted(_odoo_fields.Field.by_type)
    ]
except Exception:
    pass

from . import models
from . import wizards
