from server.core import session_scope

from fastapi import APIRouter
from server.utils.code import generate_code

code_router = APIRouter()


@code_router.get("/code")
def code():
    image, verify_code = generate_code()
    return {"image": image,
            "code": verify_code}
