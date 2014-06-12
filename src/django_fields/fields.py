import datetime
import importlib
import sys
import warnings

from django import forms
from django.forms import fields
from django.db import models
from django.conf import settings
from django.utils.encoding import smart_str
from django.utils.translation import ugettext_lazy as _

if hasattr(settings, 'USE_CPICKLE'):
    warnings.warn(
        "The USE_CPICKLE options is now obsolete. cPickle will always "
        "be used unless it cannot be found or DEBUG=True",
        DeprecationWarning,
    )

if settings.DEBUG:
    import pickle
else:
    try:
        import cPickle as pickle
    except:
        import pickle


def import_helper(name):
    class_data = name.split(".")
    module_path = ".".join(class_data[:-1])
    class_str = class_data[-1]

    module = importlib.import_module(module_path)
    # Finally, we retrieve the Class
    return getattr(module, class_str)


BaseEncryptedField = import_helper(
    getattr(
        settings,
        'DJANGO_FIELDS_BASE_FIELD',
        'django_fields.base_fields.BaseEncryptedField'
    )
)


class EncryptedTextField(BaseEncryptedField):
    __metaclass__ = models.SubfieldBase

    def get_internal_type(self):
        return 'TextField'

    def formfield(self, **kwargs):
        defaults = {'widget': forms.Textarea}
        defaults.update(kwargs)
        return super(EncryptedTextField, self).formfield(**defaults)


class EncryptedCharField(BaseEncryptedField):
    __metaclass__ = models.SubfieldBase

    def get_internal_type(self):
        return "CharField"

    def formfield(self, **kwargs):
        defaults = {'max_length': self.max_length}
        defaults.update(kwargs)
        return super(EncryptedCharField, self).formfield(**defaults)

    def get_db_prep_value(self, value, connection=None, prepared=False):
        if value is not None and not self._is_encrypted(value):
            if len(value) > self.unencrypted_length:
                raise ValueError(
                    "Field value longer than max allowed: " +
                    str(len(value)) + " > " + str(self.unencrypted_length)
                )
        return super(EncryptedCharField, self).get_db_prep_value(
            value,
            connection=connection,
            prepared=prepared,
        )


class BaseEncryptedDateField(BaseEncryptedField):
    # Do NOT define a __metaclass__ for this - it's an abstract parent
    # for EncryptedDateField and EncryptedDateTimeField.
    # If you try to inherit from a class with a __metaclass__, you'll
    # get a very opaque infinite recursion in contribute_to_class.

    def __init__(self, *args, **kwargs):
        kwargs['max_length'] = self.max_raw_length
        super(BaseEncryptedDateField, self).__init__(*args, **kwargs)

    def get_internal_type(self):
        return 'CharField'

    def formfield(self, **kwargs):
        defaults = {'widget': self.form_widget, 'form_class': self.form_field}
        defaults.update(kwargs)
        return super(BaseEncryptedDateField, self).formfield(**defaults)

    def to_python(self, value):
        # value is either a date or a string in the format "YYYY:MM:DD"

        if value in fields.EMPTY_VALUES:
            date_value = value
        else:
            if isinstance(value, self.date_class):
                date_value = value
            else:
                date_text = super(BaseEncryptedDateField, self).to_python(value)
                date_value = self.date_class(*map(int, date_text.split(':')))
        return date_value

    def get_db_prep_value(self, value, connection=None, prepared=False):
        # value is a date_class.
        # We need to convert it to a string in the format "YYYY:MM:DD"
        if value:
            date_text = value.strftime(self.save_format)
        else:
            date_text = None
        return super(BaseEncryptedDateField, self).get_db_prep_value(
            date_text,
            connection=connection,
            prepared=prepared
        )


class EncryptedDateField(BaseEncryptedDateField):
    __metaclass__ = models.SubfieldBase
    form_widget = forms.DateInput
    form_field = forms.DateField
    save_format = "%Y:%m:%d"
    date_class = datetime.date
    max_raw_length = 10  # YYYY:MM:DD


class EncryptedDateTimeField(BaseEncryptedDateField):
    # FIXME:  This doesn't handle time zones, but Python doesn't really either.
    __metaclass__ = models.SubfieldBase
    form_widget = forms.DateTimeInput
    form_field = forms.DateTimeField
    save_format = "%Y:%m:%d:%H:%M:%S:%f"
    date_class = datetime.datetime
    max_raw_length = 26  # YYYY:MM:DD:hh:mm:ss:micros


class BaseEncryptedNumberField(BaseEncryptedField):
    # Do NOT define a __metaclass__ for this - it's abstract.
    # See BaseEncryptedDateField for full explanation.
    def __init__(self, *args, **kwargs):
        if self.max_raw_length:
            kwargs['max_length'] = self.max_raw_length
        super(BaseEncryptedNumberField, self).__init__(*args, **kwargs)

    def get_internal_type(self):
        return 'CharField'

    def to_python(self, value):
        # value is either an int or a string of an integer
        if isinstance(value, self.number_type) or value == '':
            number = value
        else:
            number_text = super(BaseEncryptedNumberField, self).to_python(value)
            number = self.number_type(number_text)
        return number

    # def get_prep_value(self, value):
    def get_db_prep_value(self, value, connection=None, prepared=False):
        number_text = self.format_string % value
        return super(BaseEncryptedNumberField, self).get_db_prep_value(
            number_text,
            connection=connection,
            prepared=prepared,
        )


class EncryptedIntField(BaseEncryptedNumberField):
    __metaclass__ = models.SubfieldBase
    max_raw_length = len(str(-sys.maxint - 1))
    number_type = int
    format_string = "%d"


class EncryptedLongField(BaseEncryptedNumberField):
    __metaclass__ = models.SubfieldBase
    max_raw_length = None  # no limit
    number_type = long
    format_string = "%d"

    def get_internal_type(self):
        return 'TextField'


class EncryptedFloatField(BaseEncryptedNumberField):
    __metaclass__ = models.SubfieldBase
    max_raw_length = 150  # arbitrary, but should be sufficient
    number_type = float
    # If this format is too long for some architectures, change it.
    format_string = "%0.66f"


class PickleField(models.TextField):
    __metaclass__ = models.SubfieldBase

    editable = False
    serialize = False

    def get_db_prep_value(self, value, connection=None, prepared=False):
        return pickle.dumps(value)

    def to_python(self, value):
        if not isinstance(value, basestring):
            return value

        # Tries to convert unicode objects to string, cause loads pickle from
        # unicode excepts ugly ``KeyError: '\x00'``.
        try:
            return pickle.loads(smart_str(value))
        # If pickle could not loads from string it's means that it's Python
        # string saved to PickleField.
        except ValueError:
            return value
        except EOFError:
            return value


class EncryptedUSPhoneNumberField(BaseEncryptedField):
    __metaclass__ = models.SubfieldBase

    def get_internal_type(self):
        return "CharField"

    def formfield(self, **kwargs):
        try:
            from localflavor.us.forms import USPhoneNumberField
        except ImportError:
            from django.contrib.localflavor.us.forms import USPhoneNumberField

        defaults = {'form_class': USPhoneNumberField}
        defaults.update(kwargs)
        return super(EncryptedUSPhoneNumberField, self).formfield(**defaults)


class EncryptedUSSocialSecurityNumberField(BaseEncryptedField):
    __metaclass__ = models.SubfieldBase

    def get_internal_type(self):
        return "CharField"

    def formfield(self, **kwargs):
        try:
            from localflavor.us.forms import USSocialSecurityNumberField
        except ImportError:
            from django.contrib.localflavor.us.forms import USSocialSecurityNumberField            

        defaults = {'form_class': USSocialSecurityNumberField}
        defaults.update(kwargs)
        return super(EncryptedUSSocialSecurityNumberField, self).formfield(**defaults)

class EncryptedEmailField(BaseEncryptedField):
    __metaclass__ = models.SubfieldBase
    description = _("E-mail address")

    def get_internal_type(self):
        return "CharField"

    def formfield(self, **kwargs):
        from django.forms import EmailField
        defaults = {'form_class': EmailField, 'max_length': self.unencrypted_length}
        defaults.update(kwargs)
        return super(EncryptedEmailField, self).formfield(**defaults)


try:
    from south.modelsinspector import add_introspection_rules
    add_introspection_rules([
        (
            [
                BaseEncryptedField, EncryptedDateField, BaseEncryptedDateField, EncryptedCharField, EncryptedTextField,
                EncryptedFloatField, EncryptedDateTimeField, BaseEncryptedNumberField, EncryptedIntField, EncryptedLongField,
                EncryptedUSPhoneNumberField, EncryptedEmailField,
            ],
            [],
            {
                'cipher': ('cipher_type', {}),
                'block_type': ('block_type', {}),
            },
        ),
    ], ["^django_fields\.fields\..+?Field"])
    add_introspection_rules([], ["^django_fields\.fields\.PickleField"])
except ImportError:
    pass
