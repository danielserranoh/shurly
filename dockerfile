# Selecting a Docker Base Image
FROM python:3.10-alpine

# Copy the necessary files into the container
COPY requirements.txt requirements.txt
COPY server server
COPY main.py main.py

# Install required packages
RUN pip install --no-cache-dir -r requirements.txt

# Command to execute when running the container
CMD ["python", "main.py"]