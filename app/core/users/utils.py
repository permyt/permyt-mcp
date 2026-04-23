def set_delete_user(*args, **kwargs):
    """Set user as deleted user"""

    # Preventing circular imports | pylint: disable=import-outside-toplevel
    from .models import User

    user, _ = User.objects.get_or_create(
        username=User.DELETED_USERNAME,
        defaults={
            "first_name": "Deleted",
            "last_name": "User",
            "email": "deleted-user@permyt.io",
        },
    )
    return user
