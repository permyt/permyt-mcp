from rest_framework.renderers import JSONRenderer as RestFrameworkJSONRenderer
from .encoders import JSONEncoder


class JSONRenderer(RestFrameworkJSONRenderer):
    encoder_class = JSONEncoder
