"""
PawConnect REST API (Unit 3: Flask + Unit 2: JSON APIs).

    python main.py --api          → http://127.0.0.1:5000   (docs at /docs)

create_app() builds the Flask app: one blueprint per area (auth, cases,
donations, funds, adoption, animals, inventory, users, analytics, ...).
Route handlers are thin – they check the request, call core/workflows.py and
turn the result into JSON. Every error has the same shape:
    {"error": "message", "details": ["...", "..."]}
"""
from __future__ import annotations

import secrets

from flask import Flask
from flask_cors import CORS
from flask_smorest import Api

import config
from api.errors import register_error_handlers
from api.security import RateLimiter
from services.notification_service import OTPManager
from services.payment_razorpay import RazorpayGateway


def create_app(testing: bool = False, razorpay: RazorpayGateway | None = None,
               seed_demo: bool = True) -> Flask:
    app = Flask(__name__)
    app.config.update(
        TESTING=testing,
        JWT_SECRET=config.JWT_SECRET or secrets.token_hex(32),
        MAX_CONTENT_LENGTH=(config.MAX_PHOTO_MB + 1) * 1024 * 1024,   # bigger uploads → 413
        # ---- OpenAPI docs (flask-smorest): Swagger UI at /docs, JSON spec at /openapi.json
        API_TITLE="PawConnect API",
        API_VERSION="1.0",
        OPENAPI_VERSION="3.0.3",
        OPENAPI_URL_PREFIX="/",
        OPENAPI_JSON_PATH="openapi.json",
        OPENAPI_SWAGGER_UI_PATH="/docs",
        OPENAPI_SWAGGER_UI_URL="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.17.14/",
        API_SPEC_OPTIONS={
            "info": {"description": "Stray animal rescue, medical aid and adoption network. "
                                    "Sign in with POST /auth/login, then click **Authorize** and paste the token."},
            "security": [{"bearerAuth": []}],
            "components": {"securitySchemes": {"bearerAuth": {"type": "http", "scheme": "bearer",
                                                              "bearerFormat": "JWT"}}},
        },
    )

    app.json.sort_keys = False          # keep fields in the order we wrote them

    # Shared in-memory state: OTPs, sign-ups waiting for their OTP, rate limiters, gateway.
    app.extensions["pawconnect"] = {
        "otp": OTPManager(),
        "pending": {},
        "login_failures": RateLimiter(config.LOGIN_FAILURES_PER_MINUTE),
        "otp_sends": RateLimiter(config.OTP_SENDS_PER_MINUTE),
        "otp_verifies": RateLimiter(config.OTP_VERIFIES_PER_MINUTE),
        "razorpay": razorpay if razorpay is not None else RazorpayGateway.from_env(),
    }

    # Browsers may call the API only from the Streamlit page's origin.
    CORS(app, origins=[config.WEB_ORIGIN], supports_credentials=False)

    api = Api(app)
    from api.blueprints import adoption, admin, auth, cases, donations, funds
    for blueprint in (auth.blp, cases.blp, donations.blp, donations.payments, funds.blp,
                      adoption.animals, adoption.blp, admin.inventory, admin.users, admin.analytics,
                      admin.admin, admin.health):
        api.register_blueprint(blueprint)
    register_error_handlers(app)        # after Api(), so our error shape replaces smorest's

    from analytics import data_handler as dh
    dh.ensure_files()                   # run migrations
    if seed_demo:
        from analytics.sample_data import seed
        seed(quiet=True)                # demo data the first time only
    return app
