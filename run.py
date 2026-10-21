"""Start the dashboard:  python run.py   ->  http://127.0.0.1:5000"""
import argparse
import sys
import threading
import webbrowser

from backend import DataLoadError, create_app


def main() -> int:
    parser = argparse.ArgumentParser(description="Shopify Sales Analysis dashboard")
    parser.add_argument("--host", default="127.0.0.1", help="interface to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=5000, help="port (default: 5000)")
    parser.add_argument("--data", default=None, help="path to the sales .xlsx/.csv (default: data/Shopify_Sales_Cleaned.xlsx)")
    parser.add_argument("--no-browser", action="store_true", help="do not open the browser automatically")
    parser.add_argument("--debug", action="store_true", help="Flask debug mode (auto-reload; development only)")
    args = parser.parse_args()

    try:
        app = create_app(data_file=args.data)
    except DataLoadError as exc:
        print(f"\nERROR - could not load the sales data:\n{exc}\n", file=sys.stderr)
        return 1

    store = app.extensions["sales_store"]
    url = f"http://{args.host}:{args.port}"
    print(
        f"\nLoaded {store.quality['rows_used']:,} rows from {store.source_name} "
        f"({store.date_min} to {store.date_max}).\n"
        f"Dashboard:  {url}\n"
        f"API health: {url}/api/health\n"
        "Press CTRL+C to stop.\n"
    )
    if not args.no_browser and not args.debug:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    app.run(host=args.host, port=args.port, debug=args.debug, use_reloader=args.debug)
    return 0


if __name__ == "__main__":
    sys.exit(main())
