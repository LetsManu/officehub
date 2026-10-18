"""API errors with a stable machine-readable code the frontend can translate."""

from fastapi import HTTPException


class ApiError(HTTPException):
    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(status_code=status_code, detail=message)
        self.code = code


def not_found(what: str = "Item") -> ApiError:
    return ApiError(404, "not_found", f"{what} not found.")


def forbidden(message: str = "You do not have permission to do this.") -> ApiError:
    return ApiError(403, "forbidden", message)
