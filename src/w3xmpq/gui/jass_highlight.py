"""JASS syntax highlighting for the preview pane.

Warcraft III's scripting language (JASS) is small enough to highlight
with a handful of rules: keywords, native function names, numbers,
strings, comments and the ``//`` / ``/* */`` forms.
"""

import re

from PySide6.QtGui import (QColor, QFont, QSyntaxHighlighter, QTextCharFormat,
                            QTextDocument)

__all__ = ["JassHighlighter", "is_jass", "classify_jass", "JASS_KEYWORDS",
           "JASS_NATIVES", "ROLES"]

#: JASS keywords and type names.
JASS_KEYWORDS = {
    # control flow
    "if", "then", "else", "elseif", "endif", "loop", "endloop",
    "exitwhen", "return", "break", "continue", "when",
    # declarations
    "function", "endfunction", "constant", "native", "globals",
    "endglobals", "trigger", "endtrigger", "type", "extends",
    "local", "set", "call", "debug", "library", "endlibrary",
    "scope", "endscope", "private", "public", "static", "requires",
    "use", "initializer", "array",
    # values
    "true", "false", "nothing", "null", "and", "or", "not",
    # operators
    "plus", "minus", "times", "dividedby", "mod", "equal", "notequal",
    "greaterthan", "lessthan", "greaterthanorequal", "lessthanorequal",
    "power", "squareRoot", "radian", "degree",
    # types
    "code", "int", "integer", "real", "boolean", "string", "handle",
    "gamecache", "event", "player", "unit", "units", "item", "items",
    "location", "rect", "point", "vector", "timer", "group", "force",
    "boolexpression", "integerarray", "realarray", "stringarray",
    "triggerarray", "unitarray", "itemarray", "locationarray",
    "rectarray", "pointarray", "timerarray", "grouparray", "forcearray",
    "userdata", "agent", "dialog", "dialogfield", "texttag",
    "ability", "buff", "camera", "sound", "trigger", "effect",
    "light", "weather", "path", "rect", "location", "soundtag",
    "cameratarget", "cameratargetpoint", "condition", "func", "code",
    "jass", "typeid",
}

#: Natives that show up in almost every map.  Anything else that looks
#: like a function call is highlighted by the "camel case name + ("
#: rule, so this list only needs the very common ones for exactness.
JASS_NATIVES = {
    "CreateUnit", "RemoveUnit", "UnitDamageTarget", "UnitDamageTargetPoints",
    "SetUnitX", "SetUnitY", "GetUnitX", "GetUnitY", "SetUnitPosition",
    "GetUnitState", "SetUnitState", "GetUnitLife", "SetUnitLife",
    "GetUnitMaxLife", "SetUnitMaxLife", "GetUnitFacingAngle",
    "SetUnitFacingAngle", "KillUnit", "ShowUnit", "HideUnit",
    "SelectUnit", "PauseUnit", "ResumeUnit", "SetUnitOwner",
    "CreateItem", "RemoveItem", "SetItemPosition", "GetItemX", "GetItemY",
    "SetItemAmount", "GetItemAmount", "CreateTimer", "StartTimer",
    "PauseTimer", "ResumeTimer", "DestroyTimer", "TimerGetElapsed",
    "CreateGroup", "GroupAddUnit", "GroupRemoveUnit", "GroupClear",
    "DestroyGroup", "CreateTrigger", "TriggerRegisterUnitEvent",
    "TriggerRegisterTimerEvent", "TriggerRegisterPlayerChatEvent",
    "TriggerRegisterUnitDialogEvent", "TriggerRegisterLifeEvent",
    "TriggerRegisterDeathEvent", "TriggerRegisterCondition",
    "TriggerRegisterAction", "TriggerEvaluate", "TriggerExecute",
    "TriggerDestroy", "TriggerAddAction", "TriggerRemoveAction",
    "GetTriggerUnit", "GetTriggerPlayer", "GetTriggerTimer",
    "Player", "GetPlayerId", "GetPlayerName", "GetPlayerResource",
    "SetPlayerResource", "SetPlayerAlliance", "GetPlayerAlliance",
    "GetPlayerTeam", "SetPlayerTeam", "GetPlayerState",
    "SetPlayerState", "GetPlayerHeroLevel", "GetPlayerUnitById",
    "GetUnitAbilityLevel", "SetUnitAbilityLevel", "GetUnitTypeId",
    "BlzSetUnitRealField", "BlzGetUnitRealField", "BlzSetUnitIntegerField",
    "BlzGetUnitIntegerField", "BlzSetUnitStringField",
    "BlzGetUnitStringField", "BlzSetUnitColor", "BlzGetUnitFacingAngle",
    "DisplayTextToPlayer", "DisplayTimedTextToPlayer", "CheatMessage",
    "GetLocalPlayer", "GetTriggerPlayer", "ConvertIntegerToReal",
    "ConvertRealToInteger", "RMaxBJ", "RMinBJ", "SquareRoot",
    "GetGameTime", "TimerStart", "GetRandomUnitX", "GetRandomLocX",
    "GetRandomReal", "GetRandomPointInRect", "GetRandomPointInUnitCircle",
    "DistanceBetweenPoints", "AngleBetweenPoints", "SquareRoot",
    "I2R", "R2I", "AbsI", "AbsR", "Max", "Min", "ModuloInteger",
    "Integer2String", "Real2String", "StringHash", "SubString",
    "StringLength", "StrLen", "GetLocalizedString", "FormatString",
    "CountWordsInString", "S2I", "StringCase", "ReplaceString",
    "ConcatenateStrings", "Sweep", "GroupCountUnits",
    "SetRectFromPoints", "CreateRect", "RemoveRect", "GetRectMinX",
    "GetRectMaxX", "GetRectMinY", "GetRectMaxY", "MoveRect",
    "SetRectWidth", "SetRectHeight", "IsUnitInRect", "GetRectCenterX",
    "GetRectCenterY", "UnitFacingAngle", "GetUnitPosition",
    "GetSpellTargetUnit", "GetSpellTargetPos", "GetSpellAbilityId",
    "GetSpellLevel", "GetAbilityId", "GetSpellName",
    "IsUnitPlayer", "IsUnitAlly", "IsUnitEnemy", "IsUnitType",
    "IsUnitDead", "IsUnitHidden", "GetUnitScale", "SetUnitScale",
    "SetUnitScaleX", "SetUnitScaleY", "SetUnitX", "SetUnitY",
    "GetLocalPlayer", "ConvertIntegerToString", "MoveRect",
    "SetUnitPathing", "GetUnitFacingAngle", "SetUnitVelocity",
    "AddItemToUnit", "RemoveItemFromUnit", "GetItemUserData",
    "SetItemUserData", "GetUnitUserData", "SetUnitUserData",
    "GetTriggerUnit", "GetOrderUnit", "GetIssuedOrderId",
    "GetOrderX", "GetOrderY", "GetOrderTargetUnit",
    "CreateFogModifier", "StartFog", "StopFog", "DestroyFogModifier",
    "SetFogColor", "SetFogStart", "SetFogEnd", "SetFogDensity",
    "SaveGame", "ReloadGame", "RestartGame", "ExitGame",
    "CustomScriptText", "CustomScriptCode", "DoNothing",
    "SetCameraTargetPosition", "SetCameraPosition", "PanCameraToPoint",
    "SetCameraZoom", "SetCameraZoomLevel", "SetCinematicCamera",
    "SetCameraFieldOfView", "SetCameraTargetPosition",
    "PlaySound", "PlaySoundAtPoint", "CreateSound", "DestroySound",
    "SetSoundVolume", "SetSoundPitch", "SetSoundDuration", "SetSoundPosition",
    "UnitAddItem", "UnitDropItem", "UnitUseItem",
    "BlzSetItemSkin", "BlzGetItemSkin", "BlzSetItemSkinColor",
    "BlzGetItemRealField", "BlzSetItemRealField",
    "BlzGetUnitSkin", "BlzSetUnitSkin", "BlzSetUnitModel",
    "BlzSetItemName", "BlzSetItemDescription", "BlzSetItemTooltip",
    "BlzGetItemDescription", "BlzGetItemTooltip",
    "GetLocalizedHotkey", "GetLocalizedName",
    "CheckForPlayer", "CheckForForceInRect", "CheckForForceInLoc",
    "GetUnitsInGroup", "UnitCountInGroup", "UnitsInGroup",
    "RecycleUnit", "SetUnitX", "SetUnitY",
    "StoreItemGameCache", "StoreUnitGameCache", "StoreIntegerGameCache",
    "StoreRealGameCache", "StoreStringGameCache", "StoreBooleanGameCache",
    "LoadItemGameCache", "LoadUnitGameCache", "LoadIntegerGameCache",
    "LoadRealGameCache", "LoadStringGameCache", "LoadBooleanGameCache",
    "FlushGameCache", "SyncStoredIntegerGameCache",
    "SyncStoredRealGameCache", "SyncStoredStringGameCache",
    "SyncStoredBooleanGameCache", "SyncStoredUnitGameCache",
    "SyncStoredItemGameCache", "GameCacheInit",
}

_KEYWORDS_RE = re.compile(r"\b(%s)\b" % "|".join(
    sorted((re.escape(k) for k in JASS_KEYWORDS), key=len, reverse=True)))
_NATIVES_RE = re.compile(r"\b(%s)\b" % "|".join(
    sorted((re.escape(k) for k in JASS_NATIVES), key=len, reverse=True)))
_CALL_RE = re.compile(r"\b([A-Z][A-Za-z0-9_]{2,})\s*(?=\()")
_NUMBER_RE = re.compile(r"\b(0[xX][0-9a-fA-F]+|\d+\.\d+|\d+)\b")
_STRING_RE = re.compile(r"\"[^\"\n]*\"")
_COMMENT_RE = re.compile(r"//[^\n]*")
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.S)
_PREPROCESSOR_RE = re.compile(r"^\s*(#\w+)")

#: File extensions that hold JASS source.
_JASS_EXT = (".j", ".jass", ".w3j")

#: The roles a span can have, in the order they are detected.
ROLES = ("comment", "string", "keyword", "native", "number", "call",
         "preproc")


def is_jass(name: str) -> bool:
    """True when `name` looks like a JASS script."""
    lowered = (name or "").lower()
    return lowered.endswith(_JASS_EXT)


def classify_jass(text: str):
    """Split a line of JASS into coloured spans.

    Returns a list of ``(start, length, role)`` tuples.  Comments and
    strings are detected first and swallow whatever they contain, so a
    keyword inside a comment is not highlighted twice.

    The function is deliberately free of Qt so that it can be unit
    tested without a running application.
    """
    spans = []
    covered = []

    def add(pattern, role):
        for match in pattern.finditer(text):
            start, end = match.start(), match.end()
            if any(start < ce and cs < end for cs, ce in covered):
                continue
            spans.append((start, end - start, role))
            covered.append((start, end))

    add(_BLOCK_COMMENT_RE, "comment")
    add(_COMMENT_RE, "comment")
    add(_STRING_RE, "string")
    add(_KEYWORDS_RE, "keyword")
    add(_NATIVES_RE, "native")
    add(_CALL_RE, "call")
    add(_NUMBER_RE, "number")
    match = _PREPROCESSOR_RE.match(text)
    if match:
        spans.append((match.start(), match.end() - match.start(), "preproc"))
    spans.sort()
    return spans


class JassHighlighter(QSyntaxHighlighter):
    """Colours JASS source: keywords, natives, comments, strings.

    NOTE: this class deliberately does **not** override ``__init__``.
    In PySide6, calling ``super().__init__(document)`` from a Python
    subclass binds the QObject-parent overload instead of the
    QTextDocument overload, and the highlighter then never runs.
    """

    #: Light-theme colours: (hex, bold, italic).
    _COLOURS = {
        "keyword": ("#0b5394", True, False),
        "native": ("#7a3e9d", False, False),
        "call": ("#8a5a00", False, False),
        "comment": ("#1a7f37", False, True),
        "string": ("#b35900", False, False),
        "number": ("#0f7b6c", False, False),
        "preproc": ("#8250df", True, False),
    }

    #: Dark-theme colours — same hues, lifted for a near-black background.
    _COLOURS_DARK = {
        "keyword": ("#7cb7f0", True, False),
        "native": ("#c99bef", False, False),
        "call": ("#e0b060", False, False),
        "comment": ("#7ec699", False, True),
        "string": ("#f0a35e", False, False),
        "number": ("#5fd3c0", False, False),
        "preproc": ("#c4a0ff", True, False),
    }

    def highlightBlock(self, text: str):                    # noqa: N802
        for start, length, role in classify_jass(text):
            self.setFormat(start, length, self._fmt(role))

    # -- helpers ---------------------------------------------------------
    def _fmt(self, role):
        """Format for a role, built on first use (QApplication exists)."""
        fmt = getattr(self, "_f_" + role, None)
        if fmt is None:
            from .theme import is_dark
            table = self._COLOURS_DARK if is_dark() else self._COLOURS
            color, bold, italic = table[role]
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(color))
            if bold:
                fmt.setFontWeight(QFont.Bold)
            if italic:
                fmt.setFontItalic(True)
            setattr(self, "_f_" + role, fmt)
        return fmt
