import os

try:  # optional: load settings from a local .env file
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from app import create_app  # noqa: E402

app = create_app()

if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG", "1") == "1", port=int(os.environ.get("PORT", 5000)))
