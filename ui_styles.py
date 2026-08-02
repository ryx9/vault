"""Textual CSS for the dashboard."""

CSS = """
Screen, Screen > * {
    background: transparent;
}

Horizontal, Vertical, ScrollableContainer, Container {
    background: transparent;
}

ListView, ListItem, ListItem > Static {
    background: transparent;
    color: ansi_default;
}

RichLog {
    background: transparent;
    color: ansi_default;
}

Input {
    background: transparent;
    border: none;
    height: 1;
    padding: 0;
    color: ansi_default;
}

Input:focus {
    background: transparent;
    border: none;
    color: ansi_default;
}

Input:ansi {
    background: ansi_default;
    color: ansi_default;
}

Input > .input--cursor,
Input:ansi > .input--cursor {
    background: ansi_white;
    color: ansi_black;
}

Input > .input--selection,
Input:ansi > .input--selection {
    background: ansi_white;
    color: ansi_black;
}

Input > .input--placeholder,
Input > .input--suggestion,
Input:ansi > .input--placeholder,
Input:ansi > .input--suggestion {
    color: ansi_default;
    text-style: dim;
}

Label, Static {
    background: transparent;
    color: ansi_default;
}

* {
    scrollbar-background: transparent;
    scrollbar-color: $foreground 30%;
    scrollbar-corner-color: transparent;
}

Screen { layout: vertical; }

#header {
    dock: top;
    height: 1;
    padding: 0 1;
    content-align: left middle;
    text-style: bold;
    border-bottom: tall $foreground 20%;
}

#main { height: 1fr; }

.panel { border: none; margin: 0; padding: 0; }
.panel-title {
    padding: 0 1;
    height: 1;
    border-bottom: tall $foreground 20%;
    color: $text-muted;
}

#sidebar { width: 20; border-right: tall $foreground 20%; }
#sidebar:focus-within { border-right: tall $accent; }
#sidebar_list { height: 1fr; border: none; padding: 0; }

#sidebar_list > ListItem {
    padding: 0 1;
    background: transparent;
}

#sidebar_list > ListItem.nav-active {
    border-left: tall $accent;
    background: $accent 14%;
}

#sidebar_list > ListItem.nav-active > Static {
    color: ansi_default;
    text-style: bold;
}

#sidebar_list:focus > ListItem.--highlight {
    border-left: tall $warning;
    background: $accent 30%;
    text-style: bold reverse;
}

#notes_pane { width: 1fr; border: tall $foreground 10%; }
#notes_pane:focus-within { border: tall $accent 45%; }

#search_results_bar {
    height: 1;
    padding: 0 1;
    border-bottom: tall $foreground 20%;
    display: none;
    color: $text-muted;
}

#search_results_bar.visible { display: block; }

#dashboard_list { height: 1fr; border: none; padding: 0; }

#search_list {
    height: auto;
    max-height: 14;
    border: none;
    padding: 0;
    border-top: tall $foreground 20%;
    display: none;
}

#search_list.has-results { display: block; }

#chat_pane { width: 48; border-left: tall $foreground 20%; }
#chat_pane:focus-within { border-left: tall $accent; }

#chat_log {
    height: 1fr;
    border: none;
    padding: 1 1 0 1;
}

#chat_thinking {
    height: 1;
    padding: 0 1;
    display: none;
    color: $text-muted;
}

#chat_thinking.visible { display: block; }

#chat_input_row {
    height: 1;
    layout: horizontal;
    border-top: tall $foreground 20%;
}

#chat_prompt_label {
    width: 3;
    content-align: left middle;
    padding: 0 0 0 1;
    color: $text-muted;
}

#chat_input {
    width: 1fr;
}

#dashboard_list > ListItem.--highlight,
#dashboard_list > ListItem.highlighted,
#dashboard_list > ListItem.selected,
#search_list > ListItem.--highlight,
#search_list > ListItem.highlighted,
#search_list > ListItem.selected,
#sidebar_list > ListItem.--highlight,
#sidebar_list > ListItem.highlighted,
#sidebar_list > ListItem.selected {
    border-left: tall $accent;
    background: $accent 24%;
    color: ansi_default;
    text-style: bold;
}

#dashboard_list > ListItem.--highlight > Static,
#dashboard_list > ListItem.highlighted > Static,
#dashboard_list > ListItem.selected > Static,
#search_list > ListItem.--highlight > Static,
#search_list > ListItem.highlighted > Static,
#search_list > ListItem.selected > Static,
#sidebar_list > ListItem.--highlight > Static,
#sidebar_list > ListItem.highlighted > Static,
#sidebar_list > ListItem.selected > Static {
    color: ansi_default;
    text-style: bold;
}

#dashboard_list:focus > ListItem.--highlight,
#dashboard_list:focus > ListItem.highlighted,
#dashboard_list:focus > ListItem.selected,
#search_list:focus > ListItem.--highlight,
#search_list:focus > ListItem.highlighted,
#search_list:focus > ListItem.selected,
#sidebar_list:focus > ListItem.--highlight,
#sidebar_list:focus > ListItem.highlighted,
#sidebar_list:focus > ListItem.selected {
    border-left: tall $warning;
    background: $accent 42%;
    color: ansi_default;
    text-style: bold reverse;
}

ListItem.--disabled { color: $text-muted; }

Tree:focus > .tree--guides { text-style: dim; }

#bottom_bar {
    dock: bottom;
    height: 2;
    layout: vertical;
    border-top: tall $foreground 20%;
}

#command_row {
    height: 1;
    layout: horizontal;
}

#mode_badge {
    width: 10;
    content-align: center middle;
    padding: 0 1;
    color: $text-muted;
}

#mode_badge.mode-command { color: $warning; text-style: bold; }
#mode_badge.mode-search { color: $accent; text-style: bold; }
#mode_badge.mode-chat { color: $success; text-style: bold; }

#cmd_prompt {
    width: 2;
    content-align: center middle;
    color: $warning;
    text-style: bold;
}

#cmd {
    width: 1fr;
}

#footer_meta {
    height: 1;
    layout: horizontal;
}

#status_line {
    width: 1fr;
    content-align: left middle;
    padding: 0 1;
    color: $text-muted;
}

#hints {
    height: 1;
    width: auto;
    content-align: right middle;
    padding: 0 1;
    color: $text-muted;
}
"""
