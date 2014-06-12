import binascii
import string
import warnings

from django.conf import settings
from django.db import models
from django.utils.encoding import force_unicode, smart_str

from Crypto import Random
from Crypto.Random import random


class BaseEncryptedField(models.Field):
    '''
    This code is based on the djangosnippet #1095
    You can find the original at http://www.djangosnippets.org/snippets/1095/
    '''

    def __init__(self, *args, **kwargs):
        self.cipher_type = kwargs.pop('cipher', 'AES')
        self.block_type = kwargs.pop('block_type', None)
        self.secret_key = kwargs.pop('secret_key', settings.SECRET_KEY)
        self.secret_key = self.secret_key[:32]

        if self.block_type is None:
            warnings.warn(
                "Default usage of pycrypto's AES block type defaults has been "
                "deprecated and will be removed in 0.3.0 (default will become "
                "MODE_CBC). Please specify a secure block_type, such as CBC.",
                DeprecationWarning,
            )
        try:
            imp = __import__(
                'Crypto.Cipher', globals(), locals(), [self.cipher_type], -1
            )
        except:
            imp = __import__(
                'Crypto.Cipher', globals(), locals(), [self.cipher_type]
            )
        self.cipher_object = getattr(imp, self.cipher_type)
        if self.block_type:
            self.prefix = '$%s$%s$' % (self.cipher_type, self.block_type)
            self.iv = Random.new().read(self.cipher_object.block_size)
            self.cipher = self.cipher_object.new(
                self.secret_key,
                getattr(self.cipher_object, self.block_type),
                self.iv)
        else:
            self.cipher = self.cipher_object.new(self.secret_key)
            self.prefix = '$%s$' % self.cipher_type

        max_length = kwargs.get('max_length', 40)
        self.unencrypted_length = max_length
        # always add at least 2 to the max_length:
        #     one for the null byte, one for padding
        max_length += 2
        mod = max_length % self.cipher.block_size
        if mod > 0:
            max_length += self.cipher.block_size - mod
        kwargs['max_length'] = max_length * 2 + len(self.prefix)

        models.Field.__init__(self, *args, **kwargs)

    def _is_encrypted(self, value):
        return isinstance(value, basestring) and value.startswith(self.prefix)

    def _get_padding(self, value):
        # We always want at least 2 chars of padding (including zero byte),
        # so we could have up to block_size + 1 chars.
        mod = (len(value) + 2) % self.cipher.block_size
        return self.cipher.block_size - mod + 2

    def to_python(self, value):
        if self._is_encrypted(value):
            if self.block_type:
                self.iv = binascii.a2b_hex(
                    value[len(self.prefix):]
                )[:len(self.iv)]
                self.cipher = self.cipher_object.new(
                    self.secret_key,
                    getattr(self.cipher_object, self.block_type),
                    self.iv)
                decrypt_value = binascii.a2b_hex(
                    value[len(self.prefix):]
                )[len(self.iv):]
            else:
                decrypt_value = binascii.a2b_hex(value[len(self.prefix):])
            return force_unicode(
                self.cipher.decrypt(decrypt_value).split('\0')[0]
            )
        return value

    def get_db_prep_value(self, value, connection=None, prepared=False):
        if value is None:
            return None

        value = smart_str(value)

        if not self._is_encrypted(value):
            padding = self._get_padding(value)
            if padding > 0:
                value += "\0" + ''.join([
                    random.choice(string.printable)
                    for index in range(padding - 1)
                ])
            if self.block_type:
                self.cipher = self.cipher_object.new(
                    self.secret_key,
                    getattr(self.cipher_object, self.block_type),
                    self.iv)
                value = self.prefix + binascii.b2a_hex(
                    self.iv + self.cipher.encrypt(value)
                )
            else:
                value = self.prefix + binascii.b2a_hex(
                    self.cipher.encrypt(value)
                )
        return value
