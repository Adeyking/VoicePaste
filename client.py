from voicepaste.engine import main_cli
from voicepaste.single_instance import SingleInstanceGuard


if __name__ == "__main__":
    guard = SingleInstanceGuard()
    try:
        guard.acquire()
    except RuntimeError as exc:
        print(str(exc))
        raise SystemExit(1)

    try:
        main_cli()
    finally:
        guard.release()
