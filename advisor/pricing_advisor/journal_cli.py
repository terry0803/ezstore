"""管理員用：查看、解除結果不明的轉訂單紀錄（見 main 的說明）。"""
import json

from .conversion_journal import ConversionJournal


async def _linked_orders(number):
    from .backend import Backend

    backend = Backend()
    quotation = await backend.find_quotation(number)
    if quotation is None:
        return None, []
    orders = await backend.customer_orders(quotation["customer_id"])
    return quotation, [o for o in orders if o.get("quotation_id") == quotation["id"]]


def main(argv=None):
    """管理員查看、解除結果不明的轉訂單紀錄。容器裡用
    docker compose -p ezstore exec advisor uv run --no-sync python -m pricing_advisor.journal_cli list

    list：列出所有紀錄。
    resolve QT-…：重讀後端；已有這張報價單的訂單就解除（那次確實轉成了）。
    查不到訂單時，要先確認後端沒有那次交易（例如看 backend 日誌），再加 --confirmed-no-order-written 才解除。
    重灌 seed 不會清這份紀錄；錄影或示範前先 list 確認是空的。
    """
    import argparse
    import asyncio

    parser = argparse.ArgumentParser(prog="python -m pricing_advisor.journal_cli", description=main.__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    resolve = sub.add_parser("resolve")
    resolve.add_argument("quotation_number")
    resolve.add_argument("--confirmed-no-order-written", action="store_true")
    args = parser.parse_args(argv)
    journal = ConversionJournal()
    if args.command == "list":
        rows = {number: journal[number] for number in journal}
        print(json.dumps(rows, ensure_ascii=False, indent=2) if rows else "沒有結果不明的轉訂單紀錄")
        return 0
    number = args.quotation_number.strip().upper()
    if number not in journal:
        print(f"{number} 沒有紀錄")
        return 0
    quotation, linked = asyncio.run(_linked_orders(number))
    if linked:
        del journal[number]
        print(f"{number} 已經有訂單（{', '.join(o.get('order_number', str(o['id'])) for o in linked)}），紀錄解除")
        return 0
    if args.confirmed_no_order_written:
        del journal[number]
        print(f"{number} 後端查不到訂單，管理員已確認那次沒有寫入，紀錄解除")
        return 0
    print(f"{number} 後端{'找不到這張報價單' if quotation is None else '查不到訂單'}。先確認那次轉訂單沒有寫入，"
          "再加 --confirmed-no-order-written 解除。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
