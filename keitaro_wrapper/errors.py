class AppError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class KeitaroError(AppError):
    def __init__(self, message: str, status: int = 502):
        super().__init__(status, message)
