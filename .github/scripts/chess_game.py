import json
import os
import re
import urllib.parse
from pathlib import Path
import chess
from PIL import Image, ImageDraw, ImageFont

OWNER = "Krzys3n"
REPO = "Krzys3n"
ALLOW_OWNER_PLAY_WHITE = True  # Zmień na False po zakończeniu testów
STATE_PATH = Path("chess_games/state.json")
BOARD_IMG_PATH = Path("chess_images/board.png")
README_PATH = Path("README.md")

LIGHT_WOOD = (240, 217, 181)
DARK_WOOD = (181, 136, 99)
FRAME_WOOD = (58, 39, 25)
LABEL_TEXT = (242, 226, 202)
LAST_MOVE_LIGHT = (246, 224, 120)
LAST_MOVE_DARK = (196, 158, 68)

SQUARE_SIZE = 72
MARGIN = 28

PIECE_GLYPHS = {
    "P": "♙", "N": "♘", "B": "♗", "R": "♖", "Q": "♕", "K": "♔",
    "p": "♟", "n": "♞", "b": "♝", "r": "♜", "q": "♛", "k": "♚",
}


def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {
        "fen": chess.STARTING_FEN,
        "moves": [],
        "leaderboard": {},
        "score": {"community": 0, "owner": 0, "draws": 0},
    }


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def render_board_image(board: chess.Board, last_uci: str | None = None) -> None:
    BOARD_IMG_PATH.parent.mkdir(parents=True, exist_ok=True)
    size = MARGIN + SQUARE_SIZE * 8
    img = Image.new("RGB", (size, size), FRAME_WOOD)
    draw = ImageDraw.Draw(img)

    try:
        piece_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 46)
        label_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 16)
    except OSError:
        piece_font = ImageFont.load_default()
        label_font = ImageFont.load_default()

    highlight_squares: set[int] = set()
    if last_uci and len(last_uci) >= 4:
        try:
            highlight_squares.add(chess.parse_square(last_uci[:2]))
            highlight_squares.add(chess.parse_square(last_uci[2:4]))
        except ValueError:
            pass

    files = "ABCDEFGH"
    for f_idx, ch in enumerate(files):
        x = MARGIN + f_idx * SQUARE_SIZE + SQUARE_SIZE // 2 - 5
        draw.text((x, 5), ch, fill=LABEL_TEXT, font=label_font)

    for rank in range(7, -1, -1):
        row_idx = 7 - rank
        y_top = MARGIN + row_idx * SQUARE_SIZE
        draw.text((10, y_top + SQUARE_SIZE // 2 - 9), str(rank + 1), fill=LABEL_TEXT, font=label_font)

        for file in range(8):
            sq = chess.square(file, rank)
            x_left = MARGIN + file * SQUARE_SIZE
            is_light = (rank + file) % 2 == 1

            if sq in highlight_squares:
                color = LAST_MOVE_LIGHT if is_light else LAST_MOVE_DARK
            else:
                color = LIGHT_WOOD if is_light else DARK_WOOD

            draw.rectangle([x_left, y_top, x_left + SQUARE_SIZE, y_top + SQUARE_SIZE], fill=color)

            piece = board.piece_at(sq)
            if piece:
                glyph = PIECE_GLYPHS[piece.symbol()]
                bbox = draw.textbbox((0, 0), glyph, font=piece_font)
                w = bbox[2] - bbox[0]
                h = bbox[3] - bbox[1]
                px = x_left + (SQUARE_SIZE - w) / 2 - bbox[0]
                py = y_top + (SQUARE_SIZE - h) / 2 - bbox[1]
                draw.text((px, py), glyph, fill=(22, 22, 22), font=piece_font)

    img.save(BOARD_IMG_PATH)


def issue_link(uci: str) -> str:
    title = urllib.parse.quote(f"chess: {uci}")
    body = urllib.parse.quote(
        f"Ruch w szachach: `{uci}`\n\nKliknij **Create new issue**, aby wykonać ruch."
    )
    return f"https://github.com/{OWNER}/{REPO}/issues/new?title={title}&body={body}"


def render_moves_table(board: chess.Board) -> str:
    by_from: dict[str, list[str]] = {}
    for move in board.legal_moves:
        uci = move.uci()
        src = uci[:2].upper()
        dst = uci[2:].upper()
        by_from.setdefault(src, []).append(f"[{dst}]({issue_link(uci)})")

    if not by_from:
        return "Brak dostępnych ruchów."

    lines = ["| FROM | TO - kliknij ruch |", "| :---: | :--- |"]
    for src in sorted(by_from.keys()):
        lines.append(f"| **{src}** | {', '.join(by_from[src])} |")
    return "\n".join(lines)


def render_recent_moves(state: dict) -> str:
    lines = ["| Move | Who |", "| :--- | :--- |"]
    recent = state["moves"][-5:][::-1]
    if not recent:
        lines.append("| — | Partia czeka na pierwszy ruch |")
    else:
        for item in recent:
            src = item["uci"][:2].upper()
            dst = item["uci"][2:4].upper()
            lines.append(f"| {src} to {dst} | @{item['player']} |")
    return "\n".join(lines)


def render_leaderboard(state: dict) -> str:
    board_data = state.get("leaderboard", {})
    ranked = sorted(board_data.items(), key=lambda x: (-x[1], x[0].lower()))[:10]
    lines = ["| Moves | Who |", "| :---: | :--- |"]
    if not ranked:
        lines.append("| 0 | Brak zapisanych ruchów |")
    else:
        for player, count in ranked:
            lines.append(f"| {count} | @{player} |")
    return "\n".join(lines)


def render_section(state: dict) -> str:
    board = chess.Board(state["fen"])
    score = state["score"]
    is_white = board.turn == chess.WHITE

    if is_white:
        turn_banner = "👋 **Twój ruch! Zagraj białymi (dół planszy).** Każdy gość może wykonać następny ruch."
    else:
        turn_banner = f"⬛ **Kolej @{OWNER} (czarne — góra planszy).** Ruch wyłącznie dla właściciela profilu."

    if board.is_check():
        turn_banner += " ⚠️ **SZACH!**"

    return "\n".join([
        "<!-- CHESS_START -->",
        "### ♟️ Community Chess — Ty (czarne) vs Społeczność (białe)",
        "",
        turn_banner,
        "",
        f"**Wynik partii:** Społeczność **{score['community']}** : **{score['owner']}** @{OWNER} *(Remisy: {score['draws']})*",
        "",
        "![Drewniana szachownica](chess_images/board.png?raw=true)",
        "",
        "<details>",
        "<summary><b>🎯 Wybierz ruch (FROM → TO)</b></summary>",
        "",
        render_moves_table(board),
        "",
        "</details>",
        "",
        "#### Jak to działa",
        "Kliknij wybrany ruch w tabeli **FROM → TO**, a otworzy się gotowe zgłoszenie (*Issue*). Kliknij **Create new issue**, a **GitHub Actions** sprawdzi ruch, zaktualizuje drewnianą planszę i zamknie zgłoszenie. *(Inspiracja: [timburgan](https://github.com/timburgan)).*",
        "",
        "#### Ostatnie ruchy",
        "",
        render_recent_moves(state),
        "",
        "#### Ranking graczy",
        "",
        render_leaderboard(state),
        "<!-- CHESS_END -->",
    ])


def update_readme(section: str) -> None:
    readme = README_PATH.read_text(encoding="utf-8") if README_PATH.exists() else ""
    pattern = r"<!-- CHESS_START -->.*?<!-- CHESS_END -->"
    if re.search(pattern, readme, flags=re.S):
        new_readme = re.sub(pattern, section, readme, flags=re.S)
    else:
        new_readme = readme.rstrip() + "\n\n---\n\n" + section + "\n"
    README_PATH.write_text(new_readme, encoding="utf-8")


def write_output(status: str, message: str) -> None:
    out_file = os.environ.get("GITHUB_OUTPUT")
    if out_file:
        with open(out_file, "a", encoding="utf-8") as f:
            f.write(f"status={status}\n")
            f.write(f"message={message}\n")


def main() -> None:
    state = load_state()
    board = chess.Board(state["fen"])
    mode = os.environ.get("MODE", "render")
    last_uci = state["moves"][-1]["uci"] if state["moves"] else None

    if mode == "render":
        render_board_image(board, last_uci)
        save_state(state)
        update_readme(render_section(state))
        write_output("ok", "Plansza została wygenerowana.")
        return

    actor = os.environ.get("ISSUE_AUTHOR", "").strip()
    title = os.environ.get("ISSUE_TITLE", "").strip()

    match = re.match(r"^chess:\s*([a-h][1-8][a-h][1-8][qrbn]?)$", title, flags=re.I)
    if not match:
        write_output("invalid", "Nieprawidłowy format ruchu. Kliknij link ruchu w README.")
        return

    uci = match.group(1).lower()

    if board.turn == chess.BLACK and actor.lower() != OWNER.lower():
        write_output("invalid", f"Teraz kolej czarnych — ruch może wykonać tylko @{OWNER}.")
        return

    if board.turn == chess.WHITE and actor.lower() == OWNER.lower() and not ALLOW_OWNER_PLAY_WHITE:
        write_output("invalid", f"@{OWNER} gra czarnymi — białymi grają odwiedzający!")
        return

    try:
        move = chess.Move.from_uci(uci)
    except ValueError:
        write_output("invalid", f"Niepoprawny ruch: `{uci}`.")
        return

    if move not in board.legal_moves:
        write_output("invalid", f"Ruch `{uci}` jest w tej pozycji nielegalny.")
        return

    board.push(move)
    state["moves"].append({"uci": uci, "player": actor})
    leaderboard = state.setdefault("leaderboard", {})
    leaderboard[actor] = leaderboard.get(actor, 0) + 1

    if board.is_game_over():
        outcome = board.outcome()
        if outcome and outcome.winner == chess.WHITE:
            state["score"]["community"] += 1
            msg = f"🎉 Szach-mat! Społeczność (ostatni ruch: @{actor}) wygrywa! Rozpoczynamy nową partię."
        elif outcome and outcome.winner == chess.BLACK:
            state["score"]["owner"] += 1
            msg = f"👑 Szach-mat! @{OWNER} wygrywa! Rozpoczęto nową partię."
        else:
            state["score"]["draws"] += 1
            msg = "🤝 Remis! Rozpoczynamy nową partię."

        state["fen"] = chess.STARTING_FEN
        state["moves"] = []
        render_board_image(chess.Board(chess.STARTING_FEN), None)
    else:
        state["fen"] = board.fen()
        render_board_image(board, uci)
        msg = f"✅ Wykonano ruch `{uci}` przez @{actor}."

    save_state(state)
    update_readme(render_section(state))
    write_output("ok", msg)


if __name__ == "__main__":
    main()
