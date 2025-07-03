import boto3
import os
from dotenv import load_dotenv
from fastapi import HTTPException

load_dotenv()

REGION = os.getenv("AWS_REGION")
USER_POOL_ID = os.getenv("COGNITO_USER_POOL_ID")
CLIENT_ID = os.getenv("COGNITO_CLIENT_ID")

cognito = boto3.client("cognito-idp", region_name=REGION)


def sign_up_user(email: str, password: str, name: str):
    try:
        response = cognito.sign_up(
            ClientId=CLIENT_ID,
            Username=email,
            Password=password,
            UserAttributes=[
                {"Name": "email", "Value": email},
                {"Name": "name", "Value": name}
            ]
        )
        return {"message": "User sign-up initiated. Check your email for confirmation."}
    except cognito.exceptions.UsernameExistsException:
        raise HTTPException(status_code=400, detail="User already exists")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def login_user(email: str, password: str):
    try:
        response = cognito.initiate_auth(
            AuthFlow="USER_PASSWORD_AUTH",
            AuthParameters={
                "USERNAME": email,
                "PASSWORD": password
            },
            ClientId=CLIENT_ID
        )
        return {
            "access_token": response["AuthenticationResult"]["AccessToken"],
            "id_token": response["AuthenticationResult"]["IdToken"],
            "refresh_token": response["AuthenticationResult"]["RefreshToken"]
        }
    except cognito.exceptions.NotAuthorizedException:
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    except cognito.exceptions.UserNotConfirmedException:
        raise HTTPException(status_code=403, detail="User not confirmed")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

def confirm_user(email: str, code: str):
    try:
        response = cognito.confirm_sign_up(
            ClientId=CLIENT_ID,
            Username=email,
            ConfirmationCode=code
        )
        return {"message": "User successfully confirmed!"}
    except cognito.exceptions.CodeMismatchException:
        raise HTTPException(status_code=400, detail="Invalid confirmation code")
    except cognito.exceptions.ExpiredCodeException:
        raise HTTPException(status_code=400, detail="Confirmation code expired")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))