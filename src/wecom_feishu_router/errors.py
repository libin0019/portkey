class RouterError(Exception):
    def __init__(self, message: str, errcode: int = 40008) -> None:
        super().__init__(message)
        self.message = message
        self.errcode = errcode


class FeishuAPIError(RouterError):
    pass
