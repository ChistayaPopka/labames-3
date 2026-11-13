from .services import unread_messages


def chat(request):
    """Число непрочитанных сообщений для шапки сайта."""
    user = getattr(request, 'user', None)
    if user is None or not user.is_authenticated:
        return {}
    return {'header_unread': unread_messages(user).count()}
