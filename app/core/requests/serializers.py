from rest_framework import serializers


class RequestAccessSerializer(serializers.Serializer):
    description = serializers.CharField(max_length=2000)


class CheckAccessSerializer(serializers.Serializer):
    request_id = serializers.CharField(max_length=256)
