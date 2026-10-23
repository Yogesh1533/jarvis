import argparse


def main():
    parser = argparse.ArgumentParser(
        prog="jarvis", description="Jarvis — personal voice assistant"
    )
    sub = parser.add_subparsers(dest="mode")
    sub.add_parser("voice", help="always-on voice mode (default)")
    sub.add_parser("text", help="text-only chat mode, no audio stack")
    web_parser = sub.add_parser("web", help="browser chat UI on localhost")
    web_parser.add_argument("--port", type=int, default=8765)
    sub.add_parser("setup-google", help="one-time Google OAuth for Gmail + Calendar")
    args = parser.parse_args()

    mode = args.mode or "voice"
    if mode == "text":
        from . import text

        text.run()
    elif mode == "web":
        from . import web

        web.run(port=args.port)
    elif mode == "setup-google":
        from . import google_auth

        google_auth.run_setup()
    else:
        from . import voice

        voice.run()


if __name__ == "__main__":
    main()
