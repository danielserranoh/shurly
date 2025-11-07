# 도커 베이스 이미지 선택
FROM python:3.10-alpine

# 필요한 파일들을 컨테이너 내부로 복사
COPY requirements.txt requirements.txt
COPY server server
COPY main.py main.py

# 필요한 패키지 설치
RUN pip install --no-cache-dir -r requirements.txt

# 컨테이너 실행시 실행할 명령어
CMD ["python", "main.py"]