from captcha.image import ImageCaptcha
from base64 import b64encode
from random import randint
from server.core.config import WIDTH, HEIGHT

captcha = ImageCaptcha(width=WIDTH, height=HEIGHT)


def generate_code():
    captcha_text = str(randint(0, 999999)).zfill(6)
    return b64encode(captcha.generate(captcha_text).getvalue()).decode("utf-8"), captcha_text
