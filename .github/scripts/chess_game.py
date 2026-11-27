from datetime import datetime, timezone
import json
import os
import re
import secrets
import urllib.parse
from pathlib import Path
import chess
import chess.pgn
from PIL import Image, ImageDraw, ImageFont

OWNER = "Krzys3n"
REPO = "Krzys3n"
ALLOW_OWNER_PLAY_WHITE = False  # Set to False after testing
STATE_PATH = Path("chess_games/state.json")
HISTORY_DIR = Path("chess_games/history")
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


def get_surrender_count(state: dict) -> int:
    if isinstance(state.get("surrender_votes_count"), int):
        return max(0, state["surrender_votes_count"])
    votes = state.get("surrender_votes")
    if isinstance(votes, list):
        return len(votes)
    return 0


def load_state() -> dict:
    if STATE_PATH.exists():
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    else:
        state = {
            "fen": chess.STARTING_FEN,
            "moves": [],
            "leaderboard": {},
            "score": {"guests": 0, "owner": 0, "draws": 0},
            "surrender_votes_count": 0,
            "last_surrender_voter": None,
            "game_number": 1,
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

    count = get_surrender_count(state)
    state["surrender_votes_count"] = count
    state.pop("surrender_votes", None)

    last_voter = state.get("last_surrender_voter")
    if isinstance(last_voter, str) and last_voter.strip():
        state["last_surrender_voter"] = last_voter.strip().lstrip("@")
    else:
        state["last_surrender_voter"] = None

    game_number = state.get("game_number", 1)
    if not isinstance(game_number, int) or game_number < 1:
        state["game_number"] = 1

    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    return state


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def archive_finished_game(state: dict, reason: str, pgn_result: str) -> str | None:
    board_moves = [m for m in state.get("moves", []) if m.get("type") != "surrender" and m.get("uci")]
    surrender_count = get_surrender_count(state)

    if not board_moves and surrender_count == 0:
        return None

    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    game_num = state.get("game_number", 1)
    stem = f"game_{game_num:03d}"

    replay_board = chess.Board()
    pgn_game = chess.pgn.Game()
    pgn_game.headers["Event"] = f"{OWNER} Community Chess #{game_num}"
    pgn_game.headers["Site"] = f"https://github.com/{OWNER}/{REPO}"
    pgn_game.headers["Date"] = datetime.now(timezone.utc).strftime("%Y.%m.%d")
    pgn_game.headers["Round"] = str(game_num)
    pgn_game.headers["White"] = "Guests"
    pgn_game.headers["Black"] = OWNER
    pgn_game.headers["Result"] = pgn_result

    node = pgn_game
    move_log = []
    for idx, item in enumerate(board_moves, start=1):
        uci = item["uci"]
        player = item["player"]
        try:
            move = chess.Move.from_uci(uci)
        except ValueError:
            continue
        if move not in replay_board.legal_moves:
            continue
        san = replay_board.san(move)
        replay_board.push(move)
        node = node.add_variation(move)
        node.comment = f"@{player}"
        move_log.append({
            "ply": idx,
            "uci": uci,
            "san": san,
            "player": player,
        })

    pgn_path = HISTORY_DIR / f"{stem}.pgn"
    exporter = chess.pgn.FileExporter(pgn_path.open("w", encoding="utf-8"))
    pgn_game.accept(exporter)

    unique_guests = sorted({
        m["player"] for m in move_log if m["player"].lower() != OWNER.lower()
    }, key=str.lower)

    stats = {
        "game_number": game_num,
        "ended_at_utc": datetime.now(timezone.utc).isoformat(),
        "reason": reason,
        "pgn_result": pgn_result,
        "total_plies": len(move_log),
        "unique_guests_count": len(unique_guests),
        "unique_guests": unique_guests,
        "surrender_votes_count": surrender_count,
        "score_after": dict(state.get("score", {})),
        "moves": move_log,
    }

    json_path = HISTORY_DIR / f"{stem}.json"
    json_path.write_text(json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8")

    state["game_number"] = game_num + 1
    return stem


def cleanup_old_boards(keep_path: Path) -> None:
    if not BOARD_DIR.exists():
        return
    for file_path in BOARD_DIR.iterdir():
        if file_path.is_file() and file_path.resolve() != keep_path.resolve():
            if file_path.name.startswith("board") and file_path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
                file_path.unlink(missing_ok=True)


def render_board_image(board: chess.Board, state: dict, last_uci: str | None = None) -> str:
    BOARD_DIR.mkdir(parents=True, exist_ok=True)
    step_num = sum(1 for m in state.get("moves", []) if m.get("type") != "surrender")
    move_part = last_uci.lower() if last_uci else "start"
    token = secrets.token_hex(4)
    rel_path = f"chess_images/board_{step_num}_{move_part}_{token}.png"
    out_path = Path(rel_path)

    label_band = 28
    outer_border = 8
    board_px = SQUARE_SIZE * 8
    total_w = board_px + 2 * (outer_border + label_band)
    total_h = board_px + 2 * (outer_border + label_band)

    img = Image.new("RGB", (total_w, total_h), FRAME_WOOD)
    draw = ImageDraw.Draw(img)

    try:
        piece_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 46)
        label_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 15)
    except OSError:
        piece_font = ImageFont.load_default()
        label_font = ImageFont.load_default()

    # Dekoracyjna ramka zewnętrzna
    draw.rectangle(
        [outer_border // 2, outer_border // 2, total_w - outer_border // 2 - 1, total_h - outer_border // 2 - 1],
        outline=DARK_WOOD,
        width=2,
    )

    origin_x = outer_border + label_band
    origin_y = outer_border + label_band

    highlight_squares: set[int] = set()
    if last_uci and len(last_uci) >= 4:
        try:
            highlight_squares.add(chess.parse_square(last_uci[:2]))
            highlight_squares.add(chess.parse_square(last_uci[2:4]))
        except ValueError:
            pass

    files = "ABCDEFGH"
    top_label_y = outer_border + (label_band - 16) // 2
    bottom_label_y = origin_y + board_px + (label_band - 16) // 2

    for f_idx, ch in enumerate(files):
        x_left = origin_x + f_idx * SQUARE_SIZE
        bbox = draw.textbbox((0, 0), ch, font=label_font)
        cw = bbox[2] - bbox[0]
        cx = x_left + (SQUARE_SIZE - cw) / 2 - bbox[0]
        draw.text((cx, top_label_y), ch, fill=LABEL_TEXT, font=label_font)
        draw.text((cx, bottom_label_y), ch, fill=LABEL_TEXT, font=label_font)

    left_label_x = outer_border + 6
    right_label_x = origin_x + board_px + 6

    for rank in range(7, -1, -1):
        row_idx = 7 - rank
        y_top = origin_y + row_idx * SQUARE_SIZE
        rank_str = str(rank + 1)

        bbox_r = draw.textbbox((0, 0), rank_str, font=label_font)
        rh = bbox_r[3] - bbox_r[1]
        ry = y_top + (SQUARE_SIZE - rh) / 2 - bbox_r[1]

        draw.text((left_label_x, ry), rank_str, fill=LABEL_TEXT, font=label_font)
        draw.text((right_label_x, ry), rank_str, fill=LABEL_TEXT, font=label_font)

        for file in range(8):
            sq = chess.square(file, rank)
            x_left = origin_x + file * SQUARE_SIZE
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

                if piece.color == chess.WHITE:
                    pad = int(SQUARE_SIZE * 0.24)
                    draw.ellipse(
                        [
                            x_left + pad,
                            y_top + pad,
                            x_left + SQUARE_SIZE - pad,
                            y_top + SQUARE_SIZE - pad,
                        ],
                        fill=(248, 244, 236),
                        outline=(30, 24, 20),
                        width=2,
                    )
                    for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                        draw.text((px + dx, py + dy), glyph, fill=(25, 20, 16), font=piece_font)
                    draw.text((px, py), glyph, fill=(255, 252, 245), font=piece_font)
                else:
                    for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                        draw.text((px + dx, py + dy), glyph, fill=(235, 220, 195), font=piece_font)
                    draw.text((px, py), glyph, fill=(20, 20, 20), font=piece_font)

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


def surrender_issue_link() -> str:
    title = urllib.parse.quote("chess: surrender")
    body = urllib.parse.quote(
        "Vote to surrender the current game.\n\nClick **Create new issue** to submit your vote."
    )
    return f"https://github.com/{OWNER}/{REPO}/issues/new?title={title}&body={body}"


def profile_link(username: str) -> str:
    clean_user = username.strip().lstrip("@")
    return f"[@{clean_user}](https://github.com/{clean_user})"


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
            if item.get("type") == "surrender":
                lines.append(f"| 🏳️ Surrender vote | {profile_link(item['player'])} |")
            else:
                src = item["uci"][:2].upper()
                dst = item["uci"][2:4].upper()
                lines.append(f"| {src} to {dst} | {profile_link(item['player'])} |")
    return "\n".join(lines)


def render_leaderboard(state: dict) -> str:
    board_data = {
        k: v for k, v in state.get("leaderboard", {}).items() if k.lower() != OWNER.lower()
    }
    ranked = sorted(board_data.items(), key=lambda x: (-x[1], x[0].lower()))[:20]
    lines = ["| Moves | Guest |", "| :---: | :--- |"]
    if not ranked:
        lines.append("| 0 | No guest moves recorded yet |")
    else:
        for player, count in ranked:
            lines.append(f"| {count} | {profile_link(player)} |")
    return "\n".join(lines)


def render_section(state: dict, board_url: str) -> str:
    board = chess.Board(state["fen"])
    score = state["score"]
    is_white = board.turn == chess.WHITE
    votes_count = get_surrender_count(state)

    if is_white:
        turn_banner = "⬜ **Your turn! Play White (bottom).** Any guest can make the next move."
    else:
        turn_banner = f"⬛ **@{OWNER}'s turn (Black — top).** Restricted to the profile owner."

    if board.is_check():
        turn_banner += " ⚠️ **CHECK!**"

    return "\n".join([
        "<!-- CHESS_START -->",
        "### ♟️ Play chess with me!",
        "*It's **me vs. the whole world**, team up with other visitors to outsmart me and claim a win for the guests!*",
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
        f"**Surrender votes ({votes_count})** [🏳️ Vote to surrender]({surrender_issue_link()})  \n*If you feel that the position is lost, you can vote to surrender. If I see two votes in a row, I will reset the board and mark it as a win.*",
        "",
        "#### How to play",
        f"Click a move link in **FROM → TO** to open a pre-filled Issue, then click **Create new issue**. GitHub Actions validates the move, updates the board, and closes the Issue. *(Inspired by [timburgan](https://github.com/timburgan)).*",
        "",
        "#### 🤝 Fair play & community",
        "Feel free to share my profile with friends who know the rules of chess and team up with them to find the best move! As a gentleman's agreement, **no chess engines** I play my moves on my own, and you play yours with pure human brainpower.",
        "",
        "#### Last few moves",
        "",
        render_recent_moves(state),
        "",
        "#### Guest Leaderboard",
        "",
        render_leaderboard(state),
        "",
        f"📜 *Past games history (PGN & stats) will be saved [here](https://github.com/{OWNER}/{REPO}/tree/main/chess_games/history).*",
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


def get_last_board_uci(state: dict) -> str | None:
    for item in reversed(state.get("moves", [])):
        if item.get("type") != "surrender" and item.get("uci"):
            return item["uci"]
    return None


def reset_match_state(state: dict) -> chess.Board:
    state["fen"] = chess.STARTING_FEN
    state["moves"] = []
    state["surrender_votes_count"] = 0
    state["last_surrender_voter"] = None
    return chess.Board(chess.STARTING_FEN)


def main() -> None:
    state = load_state()
    board = chess.Board(state["fen"])
    mode = os.environ.get("MODE", "render")
    last_uci = get_last_board_uci(state)

    reset_mode = os.environ.get("RESET_MODE", "").strip().lower()
    legacy_reset = os.environ.get("RESET_GAME", "").strip().lower() in {"true", "1", "yes"}
    if not reset_mode and legacy_reset:
        reset_mode = "reset_only"

    if mode == "render":
        if reset_mode in {"reset_only", "owner_win", "guests_win", "draw"}:
            if reset_mode == "owner_win":
                state["score"]["owner"] += 1
                archived = archive_finished_game(state, "manual_owner_win", "0-1")
                suffix = f" Saved as {archived}." if archived else ""
                result_msg = f"Game reset — +1 win awarded to @{OWNER}.{suffix}"
            elif reset_mode == "guests_win":
                state["score"]["guests"] += 1
                archived = archive_finished_game(state, "manual_guests_win", "1-0")
                suffix = f" Saved as {archived}." if archived else ""
                result_msg = f"Game reset — +1 win awarded to Guests.{suffix}"
            elif reset_mode == "draw":
                state["score"]["draws"] += 1
                archived = archive_finished_game(state, "manual_draw", "1/2-1/2")
                suffix = f" Saved as {archived}." if archived else ""
                result_msg = f"Game reset — +1 draw recorded.{suffix}"
            else:
                archived = archive_finished_game(state, "manual_reset", "*")
                suffix = f" Saved as {archived}." if archived else ""
                result_msg = f"Game reset to starting position.{suffix}"

            board = reset_match_state(state)
            last_uci = None
        else:
            result_msg = "Board rendered."

        board_url = render_board_image(board, state, last_uci)
        save_state(state)
        update_readme(render_section(state, board_url))
        write_output("ok", result_msg)
        return

    actor = os.environ.get("ISSUE_AUTHOR", "").strip()
    title = os.environ.get("ISSUE_TITLE", "").strip()

    if re.match(r"^chess:\s*surrender$", title, flags=re.I):
        actor_clean = actor.lstrip("@")
        if not actor_clean:
            write_output("invalid", "Missing issue author.")
            return

        last_voter = state.get("last_surrender_voter")
        if isinstance(last_voter, str) and last_voter.lower() == actor_clean.lower():
            write_output("invalid", f"@{actor_clean} already cast the most recent surrender vote.")
            return

        new_count = get_surrender_count(state) + 1
        state["surrender_votes_count"] = new_count
        state["last_surrender_voter"] = actor_clean
        state["moves"].append({"type": "surrender", "player": actor_clean})
        board_url = state.get("board_image") or render_board_image(board, state, last_uci)
        save_state(state)
        update_readme(render_section(state, board_url))
        write_output("ok", f"🏳️ @{actor_clean} voted to surrender ({new_count} vote(s)).")
        return

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
    state["moves"].append({"type": "move", "uci": uci, "player": actor})

    if actor.lower() != OWNER.lower():
        leaderboard = state.setdefault("leaderboard", {})
        leaderboard[actor] = leaderboard.get(actor, 0) + 1

    if board.is_game_over():
        outcome = board.outcome()
        if outcome and outcome.winner == chess.WHITE:
            state["score"]["guests"] += 1
            archived = archive_finished_game(state, "checkmate_white", "1-0")
            suffix = f" Saved as {archived}." if archived else ""
            msg = f"🎉 Checkmate! Guests (last move: @{actor}) win the game! Starting a new game.{suffix}"
        elif outcome and outcome.winner == chess.BLACK:
            state["score"]["owner"] += 1
            archived = archive_finished_game(state, "checkmate_black", "0-1")
            suffix = f" Saved as {archived}." if archived else ""
            msg = f"👑 Checkmate! @{OWNER} wins the game! Starting a new game.{suffix}"
        else:
            state["score"]["draws"] += 1
            archived = archive_finished_game(state, "draw", "1/2-1/2")
            suffix = f" Saved as {archived}." if archived else ""
            msg = f"🤝 Game drawn! Starting a new game.{suffix}"

        board = reset_match_state(state)
        board_url = render_board_image(board, state, None)
    else:
        state["fen"] = board.fen()
        board_url = render_board_image(board, state, uci)
        msg = f"✅ Played `{uci}` by @{actor}."

    save_state(state)
    update_readme(render_section(state, board_url))
    write_output("ok", msg)


if __name__ == "__main__":
    main()
