"""
AWS Lambda handler for Shurly API.

This module provides the Lambda function handler that wraps the FastAPI application
using Mangum to make it compatible with AWS Lambda + API Gateway.
"""

from mangum import Mangum

from main import app

# Create the Lambda handler
# Mangum converts API Gateway events to ASGI format for FastAPI
handler = Mangum(app, lifespan="off")


def lambda_handler(event, context):
    """
    AWS Lambda function handler.

    Args:
        event: API Gateway event
        context: Lambda context

    Returns:
        API Gateway response
    """
    return handler(event, context)
