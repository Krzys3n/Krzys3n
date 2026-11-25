import json
import os
import re
import secrets
import urllib.parse
from pathlib import Path
import chess
from PIL import Image, ImageDraw, ImageFont

OWNER = "Krzys3n"
REPO = "Krzys3n"
ALLOW_OWNER_PLAY_WHITE = False  # Set to False after testing
STATE_PATH = Path("chess_games/state.json")
BOARD_DIR = Path("chess_images")
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
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    else:
        state = {
            "fen": chess.STARTING_FEN,
            "moves": [],
            "leaderboard": {},
            "score": {"guests": 0, "owner": 0, "draws": 0},
            "board_image": None,
        }

    score = state.setdefault("score", {})
    if "guests" not in score:
        score["guests"] = score.pop("community", 0)
    score.setdefault("owner", 0)
    score.setdefault("draws", 0)

    leaderboard = state.setdefault("leaderboard", {})
    for key in list(leaderboard.keys()):
        if key.lower() == OWNER.lower():
            del leaderboard[key]

    return state


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def cleanup_old_boards(keep_path: Path) -> None:
    if not BOARD_DIR.exists():
        return
    for file_path in BOARD_DIR.iterdir():
        if file_path.is_file() and file_path.resolve() != keep_path.resolve():
            if file_path.name.startswith("board") and file_path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
                file_path.unlink(missing_ok=True)


def render_board_image(board: chess.Board, state: dict, last_uci: str | None = None) -> str:
    BOARD_DIR.mkdir(parents=True, exist_ok=True)
    step_num = len(state.get("moves", []))
    move_part = last_uci.lower() if last_uci else "start"
    token = secrets.token_hex(4)
    rel_path = f"chess_images/board_{step_num}_{move_part}_{token}.png"
    out_path = Path(rel_path)

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

    img.save(out_path)
    cleanup_old_boards(out_path)
    state["board_image"] = rel_path
    return rel_path


def issue_link(uci: str) -> str:
    title = urllib.parse.quote(f"chess: {uci}")
    body = urllib.parse.quote(
        f"Chess move: `{uci}`\n\nClick **Create new issue** to play this move."
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
        return "No legal moves available."

    lines = ["| FROM | TO - click a move |", "| :---: | :--- |"]
    for src in sorted(by_from.keys()):
        lines.append(f"| **{src}** | {', '.join(by_from[src])} |")
    return "\n".join(lines)


def render_recent_moves(state: dict) -> str:
    lines = ["| Move | Who |", "| :--- | :--- |"]
    recent = state["moves"][-5:][::-1]
    if not recent:
        lines.append("| — | Waiting for the first move |")
    else:
        for item in recent:
            src = item["uci"][:2].upper()
            dst = item["uci"][2:4].upper()
            lines.append(f"| {src} to {dst} | @{item['player']} |")
    return "\n".join(lines)


def render_leaderboard(state: dict) -> str:
    board_data = {
        k: v for k, v in state.get("leaderboard", {}).items() if k.lower() != OWNER.lower()
    }
    ranked = sorted(board_data.items(), key=lambda x: (-x[1], x[0].lower()))[:10]
    lines = ["| Moves | Guest |", "| :---: | :--- |"]
    if not ranked:
        lines.append("| 0 | No guest moves recorded yet |")
    else:
        for player, count in ranked:
            lines.append(f"| {count} | @{player} |")
    return "\n".join(lines)


def render_section(state: dict, board_url: str) -> str:
    board = chess.Board(state["fen"])
    score = state["score"]
    is_white = board.turn == chess.WHITE

    if is_white:
        turn_banner = "⬜ **Your turn! Play White (bottom).** Any guest can make the next move."
    else:
        turn_banner = f"⬛ **@{OWNER}'s turn (Black — top).** Restricted to the profile owner."

    if board.is_check():
        turn_banner += " ⚠️ **CHECK!**"

    return "\n".join([
        "<!-- CHESS_START -->",
        f"### ♟️ Play chess with me!",
        "",
        turn_banner,
        "",
        f"**Series score:** {OWNER} **{score['owner']}** : **{score['guests']}** Guests *(Draws: {score['draws']})*",
        "",
        f"![Wooden Chessboard]({board_url})",
        "",
        "#### 🎯 Choose a move (FROM → TO)",
        "",
        render_moves_table(board),
        "",
        "#### How to play",
        f"Click a move link in **FROM → TO** to open a pre-filled Issue, then click **Create new issue**. GitHub Actions validates the move, updates the board, and closes the Issue. *(Inspired by [timburgan](https://github.com/timburgan)).*",
        "",
        "#### Last few moves",
        "",
        render_recent_moves(state),
        "",
        "#### Guest Leaderboard",
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

    reset_requested = os.environ.get("RESET_GAME", "").strip().lower() in {"true", "1", "yes"}

    if mode == "render":
        if reset_requested:
            state["fen"] = chess.STARTING_FEN
            state["moves"] = []
            board = chess.Board(chess.STARTING_FEN)
            last_uci = None
        board_url = render_board_image(board, state, last_uci)
        save_state(state)
        update_readme(render_section(state, board_url))
        write_output("ok", "Game reset to starting position." if reset_requested else "Board rendered.")
        return

    actor = os.environ.get("ISSUE_AUTHOR", "").strip()
    title = os.environ.get("ISSUE_TITLE", "").strip()

    match = re.match(r"^chess:\s*([a-h][1-8][a-h][1-8][qrbn]?)$", title, flags=re.I)
    if not match:
        write_output("invalid", "Invalid move format. Click a move link in the README.")
        return

    uci = match.group(1).lower()

    if board.turn == chess.BLACK and actor.lower() != OWNER.lower():
        write_output("invalid", f"It is Black's turn — only @{OWNER} can move Black.")
        return

    if board.turn == chess.WHITE and actor.lower() == OWNER.lower() and not ALLOW_OWNER_PLAY_WHITE:
        write_output("invalid", f"@{OWNER} plays Black — White is for guests!")
        return

    try:
        move = chess.Move.from_uci(uci)
    except ValueError:
        write_output("invalid", f"Invalid move: `{uci}`.")
        return

    if move not in board.legal_moves:
        write_output("invalid", f"Move `{uci}` is illegal in the current position.")
        return

    board.push(move)
    state["moves"].append({"uci": uci, "player": actor})

    if actor.lower() != OWNER.lower():
        leaderboard = state.setdefault("leaderboard", {})
        leaderboard[actor] = leaderboard.get(actor, 0) + 1

    if board.is_game_over():
        outcome = board.outcome()
        if outcome and outcome.winner == chess.WHITE:
            state["score"]["guests"] += 1
            msg = f"🎉 Checkmate! Guests (last move: @{actor}) win the game! Starting a new game."
        elif outcome and outcome.winner == chess.BLACK:
            state["score"]["owner"] += 1
            msg = f"👑 Checkmate! @{OWNER} wins the game! Starting a new game."
        else:
            state["score"]["draws"] += 1
            msg = "🤝 Game drawn! Starting a new game."

        state["fen"] = chess.STARTING_FEN
        state["moves"] = []
        board_url = render_board_image(chess.Board(chess.STARTING_FEN), state, None)
    else:
        state["fen"] = board.fen()
        board_url = render_board_image(board, state, uci)
        msg = f"✅ Played `{uci}` by @{actor}."

    save_state(state)
    update_readme(render_section(state, board_url))
    write_output("ok", msg)


if __name__ == "__main__":
    main()
