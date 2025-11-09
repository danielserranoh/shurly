"""Common HTTP response schemas for API documentation."""

from typing import Any

from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    """Detailed error information."""

    loc: list[str] | None = Field(
        None,
        description="Location of the error (for validation errors)",
        examples=[["body", "email"]],
    )
    msg: str = Field(..., description="Error message", examples=["Invalid email format"])
    type: str = Field(..., description="Error type", examples=["value_error.email"])


class ErrorResponse(BaseModel):
    """Standard error response format."""

    detail: str | list[ErrorDetail] = Field(
        ...,
        description="Error message or list of validation errors",
        examples=["Resource not found"],
    )

    class Config:
        json_schema_extra = {
            "examples": [
                {"detail": "Email already registered"},
                {"detail": "Invalid credentials"},
                {
                    "detail": [
                        {
                            "loc": ["body", "email"],
                            "msg": "Invalid email format",
                            "type": "value_error.email",
                        }
                    ]
                },
            ]
        }


class MessageResponse(BaseModel):
    """Simple message response."""

    message: str = Field(..., description="Response message", examples=["Operation successful"])

    class Config:
        json_schema_extra = {"examples": [{"message": "Password changed successfully"}]}


# Common HTTP response documentation
RESPONSES = {
    400: {
        "description": "Bad Request - Invalid input or validation error",
        "model": ErrorResponse,
    },
    401: {
        "description": "Unauthorized - Authentication required or invalid credentials",
        "model": ErrorResponse,
    },
    403: {
        "description": "Forbidden - Insufficient permissions to access this resource",
        "model": ErrorResponse,
    },
    404: {
        "description": "Not Found - The requested resource does not exist",
        "model": ErrorResponse,
    },
    422: {
        "description": "Unprocessable Entity - Validation error",
        "model": ErrorResponse,
    },
    500: {
        "description": "Internal Server Error - An unexpected error occurred",
        "model": ErrorResponse,
    },
}


def get_responses(*status_codes: int) -> dict[int | str, dict[str, Any]]:
    """
    Get response documentation for specific status codes.

    Usage:
        @router.get("/example", responses=get_responses(400, 404))
    """
    return {code: RESPONSES[code] for code in status_codes if code in RESPONSES}
