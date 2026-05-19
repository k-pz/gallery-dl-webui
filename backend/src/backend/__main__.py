import uvicorn

from backend.config import load_settings


def main() -> None:
    settings = load_settings()
    uvicorn.run("backend.main:app", host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
