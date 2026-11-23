# Provides the borderless subtitle window and its hover controls.

from config import Settings, application_root
from languages import SUPPORTED_TRANSLATION_LANGUAGES
from subtitles import SubtitleState
import re
import threading
from collections.abc import Callable
from pathlib import Path


# =============================================================================
#                                UI WINDOW
# =============================================================================

class SubtitleWindow:
    # Owns the Tk window that renders live subtitle lines.
    # --------------------------------------------------------------------------
    # The window remains responsive because background workers update shared state
    # while all Tk operations remain on the Tk thread.
    # --------------------------------------------------------------------------

    def __init__(
        self,
        settings: Settings,
        on_language_change: Callable[[str, str], None] | None = None,
    ) -> None:
        # Creates and configures the subtitle window widgets.
        # ----------------------------------------------------------------------
        # @param settings: Validated UI configuration applied to Tk widgets.
        # @param on_language_change: Callback receiving new source and target codes.
        # @return: None.
        # ----------------------------------------------------------------------
        # import Tk lazily so non-UI modules can be loaded in headless contexts.
        import tkinter as tk
        import tkinter.font as tkfont

        # retain configuration for later layout and style updates.
        self.settings = settings
        self._on_language_change_callback = on_language_change

        # initialize the top-level window before adding child widgets.
        self.tk = tk.Tk()
        self.tk.title("Iris - Director's Assistant")

        # remove the native title bar for a presentation overlay when requested.
        if self.settings.ui.window_borderless:
            self.tk.overrideredirect(True)

        # establish a usable fallback size before optional layout.
        self.tk.geometry("600x300")

        # apply the configured user-resize policy.
        self.tk.resizable(self.settings.ui.window_resizable, self.settings.ui.window_resizable)

        # apply the configured background before creating text widgets.
        self.tk.configure(bg=self.settings.ui.window_background_color)

        if self.settings.ui.window_borderless:
            # size the overlay as a resolution-independent stripe at the bottom
            # of the primary display rather than using a fixed pixel height.
            screen_width = self.tk.winfo_screenwidth()
            screen_height = self.tk.winfo_screenheight()
            stripe_height = max(
                1,
                round(screen_height * self.settings.ui.window_height_fraction),
            )
            self.stripe_height = stripe_height
            self.tk.geometry(
                f"{screen_width}x{stripe_height}+0+{screen_height - stripe_height}"
            )
        elif self.settings.ui.window_zoomed:
            # prefer native maximization and retain a platform-neutral fallback.
            try:
                self.tk.state("zoomed")
            except Exception:
                w = self.tk.winfo_screenwidth()
                h = self.tk.winfo_screenheight()
                self.tk.geometry(f"{w}x{h}+0+0")
            #end try

        #end if

        # keep the overlay above PowerPoint's presentation window when enabled.
        if self.settings.ui.window_keep_on_top:
            self.tk.attributes("-topmost", True)

        # apply uniform opacity after geometry and window-manager attributes.
        self.tk.attributes("-alpha", self.settings.ui.window_alpha)

        # bind Escape as a keyboard fallback while keeping shutdown on the UI thread.
        self.tk.bind_all("<Escape>", lambda e: self.tk.destroy())

        # route native window-manager close requests through the same cleanup path.
        self.tk.protocol("WM_DELETE_WINDOW", self._close_window)

        # retain the pending timer used to hide the hover-only close control.
        self._close_hide_after_id: str | None = None

        # create a compact Windows-style close button over the borderless window.
        self._close_button = tk.Button(
            self.tk,
            text="×",
            command=self._close_window,
            font=("Segoe UI", 11),
            fg="#ffffff",
            bg="#5a5a5a",
            activeforeground="#ffffff",
            activebackground="#c42b2b",
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            padx=0,
            pady=0,
            width=3,
            height=1,
            cursor="hand2",
        )
        self._close_button.place(relx=1.0, x=-5, y=5, anchor="ne")
        self._close_button.place_forget()

        # create the vertical transparency control below the close button.
        self._alpha_scale = tk.Scale(
            self.tk,
            from_=0.1,
            to=1.0,
            resolution=0.05,
            orient="vertical",
            showvalue=False,
            command=self._set_window_alpha,
            bg=self.settings.ui.window_background_color,
            fg=self.settings.ui.window_text_color,
            troughcolor="#5a5a5a",
            activebackground="#c42b2b",
            highlightthickness=0,
            borderwidth=0,
            width=12,
            length=82,
            sliderlength=18,
            cursor="hand2",
        )
        self._alpha_scale.set(self.settings.ui.window_alpha)
        self._alpha_scale.place(relx=1.0, x=-5, y=34, anchor="ne")
        self._alpha_scale.place_forget()

        # retain the two interactive subtitle colors for tag and swatch updates.
        self._new_text_color = self.settings.ui.window_new_text_color
        self._old_text_color = self.settings.ui.window_text_color

        # create vertically aligned color swatches beside the transparency scale.
        self._new_color_button = tk.Button(
            self.tk,
            command=self._choose_new_text_color,
            bg=self._new_text_color,
            activebackground=self._new_text_color,
            relief="raised",
            borderwidth=1,
            highlightthickness=0,
            width=2,
            height=1,
            cursor="hand2",
        )
        self._old_color_button = tk.Button(
            self.tk,
            command=self._choose_old_text_color,
            bg=self._old_text_color,
            activebackground=self._old_text_color,
            relief="raised",
            borderwidth=1,
            highlightthickness=0,
            width=2,
            height=1,
            cursor="hand2",
        )
        self._new_color_button.place(relx=1.0, x=-28, y=38, anchor="ne")
        self._old_color_button.place(relx=1.0, x=-28, y=58, anchor="ne")
        self._new_color_button.place_forget()
        self._old_color_button.place_forget()

        # create minimal source and target dropdowns below the color swatches.
        self._source_language_var = tk.StringVar(
            value=self.settings.translation.source_language
        )
        self._target_language_var = tk.StringVar(
            value=self.settings.translation.target_language
        )
        self._source_language_menu = tk.OptionMenu(
            self.tk,
            self._source_language_var,
            *SUPPORTED_TRANSLATION_LANGUAGES,
            command=self._on_source_language_selected,
        )
        self._target_language_menu = tk.OptionMenu(
            self.tk,
            self._target_language_var,
            *SUPPORTED_TRANSLATION_LANGUAGES,
            command=self._on_target_language_selected,
        )
        for menu in (self._source_language_menu, self._target_language_menu):
            # keep the menus compact while preserving readable language codes.
            menu.configure(
                width=3,
                height=1,
                font=("Segoe UI", 8),
                padx=0,
                pady=0,
                bg="#5a5a5a",
                fg="#ffffff",
                activebackground="#c42b2b",
                activeforeground="#ffffff",
                relief="raised",
                borderwidth=1,
                highlightthickness=0,
                cursor="hand2",
            )
        self._source_language_menu.place(relx=1.0, x=-28, y=78, anchor="ne")
        self._target_language_menu.place(relx=1.0, x=-28, y=103, anchor="ne")
        self._source_language_menu.place_forget()
        self._target_language_menu.place_forget()

        # detect motion over both the text surface and the close control.
        self.tk.bind("<Motion>", self._on_mouse_motion, add="+")

        # retain a Tk variable for compatibility with existing window state.
        self.var = tk.StringVar(value="")

        # create a mutable Tk font; its final size is fitted to the actual
        # subtitle content and the available width/height during rendering.
        if self.settings.ui.window_borderless:
            self.display_font = tkfont.Font(
                self.tk,
                family=self.settings.ui.window_font_family,
                size=1,
                weight=self.settings.ui.window_font_weight,
            )
        else:
            self.display_font = (
                self.settings.ui.window_font_family,
                self.settings.ui.window_font_size,
                self.settings.ui.window_font_weight,
            )

        # create the styled text widget that renders subtitle snapshots.
        self.text = tk.Text(
            self.tk,
            bg=self.settings.ui.window_background_color,
            fg=self.settings.ui.window_text_color,
            font=self.display_font,
            # Wrapping is performed explicitly below using the real Tk font
            # metrics.  Native Text wrapping would wrap the already formatted
            # subtitle lines a second time and make height=2 show only the
            # bottom line.
            wrap="none",
            height=max(1, self.settings.ui.max_lines_on_screen),
            borderwidth=0,
            highlightthickness=0,
            spacing1=0,
            spacing2=0,
            spacing3=0,
        )
        self.text.pack(
            expand=True,
            fill="both",
            padx=self.settings.ui.window_text_padding_x,
            pady=self.settings.ui.window_text_padding_y,
        )
        self.text.bind("<Motion>", self._on_mouse_motion, add="+")
        self._close_button.bind("<Motion>", self._on_mouse_motion, add="+")
        self._alpha_scale.bind("<Motion>", self._on_mouse_motion, add="+")
        self._new_color_button.bind("<Motion>", self._on_mouse_motion, add="+")
        self._old_color_button.bind("<Motion>", self._on_mouse_motion, add="+")
        self._source_language_menu.bind("<Motion>", self._on_mouse_motion, add="+")
        self._target_language_menu.bind("<Motion>", self._on_mouse_motion, add="+")

        self.text.tag_configure("center", justify="center")

        # define tags that distinguish historical and newest subtitle lines.
        self.text.tag_configure("normal", foreground=self._old_text_color)
        self.text.tag_configure("last", foreground=self._new_text_color)

        # retain the last rendered rows so repeated UI ticks do not rewrite the
        # Text widget and visibly blink while no new subtitle has arrived.
        self._rendered_visual_lines: list[tuple[str, bool]] = []
        # retain the input used for the last borderless font/wrapping fit so
        # trial font sizes are not applied repeatedly on every UI tick.
        self._fit_signature: tuple[tuple[str, bool], ...] | None = None

        # show the bundled logo as a centered startup watermark for three seconds.
        self._watermark_after_id: str | None = None
        self._show_startup_watermark()
    #end def


    def _on_source_language_selected(self, value: str) -> None:
        # Sends a newly selected spoken language to the streaming worker.
        # ----------------------------------------------------------------------
        # @param value: Selected source language code.
        # @return: None.
        # ----------------------------------------------------------------------
        self._notify_language_change(value, self._target_language_var.get())
    #end def


    def _on_target_language_selected(self, value: str) -> None:
        # Sends a newly selected subtitle language to the streaming worker.
        # ----------------------------------------------------------------------
        # @param value: Selected target language code.
        # @return: None.
        # ----------------------------------------------------------------------
        self._notify_language_change(self._source_language_var.get(), value)
    #end def


    def _notify_language_change(self, source_language: str, target_language: str) -> None:
        # Forwards a complete language direction to the worker callback.
        # ----------------------------------------------------------------------
        # @param source_language: New spoken language code.
        # @param target_language: New subtitle language code.
        # @return: None.
        # ----------------------------------------------------------------------
        if self._on_language_change_callback is not None:
            self._on_language_change_callback(source_language, target_language)
    #end def


    def _set_window_alpha(self, value: str) -> None:
        # Applies the slider's transparency value to the whole subtitle window.
        # ----------------------------------------------------------------------
        # The slider value is delivered as text by Tk and is constrained to the
        # configured range before being passed to the window manager.
        # @param value: Requested opacity from 0.1 through 1.0.
        # @return: None.
        # ----------------------------------------------------------------------
        import tkinter as tk

        try:
            alpha = max(0.1, min(1.0, float(value)))
            self.tk.attributes("-alpha", alpha)
        except (TypeError, ValueError, tk.TclError):
            # Ignore transient widget values or unsupported window-manager alpha.
            pass
    #end def


    def _choose_new_text_color(self) -> None:
        # Opens the color chooser for the newest subtitle line color.
        # ----------------------------------------------------------------------
        # @return: None.
        # ----------------------------------------------------------------------
        self._choose_text_color("new")
    #end def


    def _show_startup_watermark(self) -> None:
        # Displays the bundled logo over the subtitle window temporarily.
        # ----------------------------------------------------------------------
        # Pillow is loaded lazily because the logo is optional during source
        # inspection and the application should still start if it cannot load.
        # @return: None.
        # ----------------------------------------------------------------------
        try:
            import tkinter as tk
            from PIL import Image, ImageTk

            logo_path = application_root() / Path("assets/logo-fgu-en.webp")
            if not logo_path.exists():
                return

            # resize large source artwork while preserving its aspect ratio.
            image = Image.open(logo_path).convert("RGBA")
            max_width = max(160, int(self.tk.winfo_screenwidth() * 0.35))
            max_height = max(80, int(getattr(self, "stripe_height", 240) * 0.70))
            image.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)

            # reduce alpha so the startup artwork behaves like a watermark.
            alpha = image.getchannel("A").point(lambda value: int(value * 0.45))
            image.putalpha(alpha)
            self._watermark_photo = ImageTk.PhotoImage(image)
            self._watermark_label = tk.Label(
                self.tk,
                image=self._watermark_photo,
                bg=self.settings.ui.window_background_color,
                borderwidth=0,
                highlightthickness=0,
            )
            self._watermark_label.place(relx=0.5, rely=0.5, anchor="center")
            self._watermark_label.bind("<Motion>", self._on_mouse_motion, add="+")
            self._watermark_after_id = self.tk.after(3000, self._remove_startup_watermark)
        except Exception as error:
            # keep the subtitle window usable if Pillow or the bundled asset fails.
            print(f"Startup watermark unavailable: {error}")
    #end def


    def _remove_startup_watermark(self) -> None:
        # Removes the startup watermark after its three-second display period.
        # ----------------------------------------------------------------------
        # Drop the widget and image reference so the logo no longer covers the
        # subtitle surface and its memory can be reclaimed by Tk/Pillow.
        # @return: None.
        # ----------------------------------------------------------------------
        self._watermark_after_id = None
        if getattr(self, "_watermark_label", None) is not None:
            self._watermark_label.destroy()
            self._watermark_label = None
        self._watermark_photo = None
    #end def


    def _choose_old_text_color(self) -> None:
        # Opens the color chooser for older subtitle line colors.
        # ----------------------------------------------------------------------
        # @return: None.
        # ----------------------------------------------------------------------
        self._choose_text_color("old")
    #end def


    def _choose_text_color(self, role: str) -> None:
        # Applies a selected color to the matching subtitle tag and swatch.
        # ----------------------------------------------------------------------
        # The native chooser returns no color when the user cancels, leaving the
        # current tag and button unchanged.
        # @param role: Either "new" for the newest line or "old" for older lines.
        # @return: None.
        # ----------------------------------------------------------------------
        import tkinter.colorchooser as colorchooser

        current_color = self._new_text_color if role == "new" else self._old_text_color
        selected = colorchooser.askcolor(
            color=current_color,
            parent=self.tk,
            title="Choose newest text color" if role == "new" else "Choose older text color",
        )[1]
        if not selected:
            return

        # update the selected role and immediately recolor existing tagged text.
        if role == "new":
            self._new_text_color = selected
            self._new_color_button.configure(
                bg=selected,
                activebackground=selected,
            )
            self.text.tag_configure("last", foreground=selected)
        else:
            self._old_text_color = selected
            self._old_color_button.configure(
                bg=selected,
                activebackground=selected,
            )
            self.text.tag_configure("normal", foreground=selected)
    #end def


    def _close_window(self) -> None:
        # Destroys the window so the application boundary can release the microphone.
        # ----------------------------------------------------------------------
        # Tk destruction returns control to translator_main(), whose finally block
        # signals the worker and closes the shared audio stream.
        # @return: None.
        # ----------------------------------------------------------------------
        if self._close_hide_after_id is not None:
            self.tk.after_cancel(self._close_hide_after_id)
            self._close_hide_after_id = None
        if self._watermark_after_id is not None:
            self.tk.after_cancel(self._watermark_after_id)
            self._watermark_after_id = None
        if self.tk.winfo_exists():
            self.tk.destroy()
    #end def


    def _hide_close_button(self) -> None:
        # Hides the close control after the hover period expires.
        # ----------------------------------------------------------------------
        # Keep the button available only while the user is actively moving across
        # the subtitle surface, preventing it from obscuring translated text.
        # @return: None.
        # ----------------------------------------------------------------------
        self._close_hide_after_id = None
        if self.tk.winfo_exists():
            self._close_button.place_forget()
            self._alpha_scale.place_forget()
            self._new_color_button.place_forget()
            self._old_color_button.place_forget()
            self._source_language_menu.place_forget()
            self._target_language_menu.place_forget()
    #end def


    def _show_close_button(self) -> None:
        # Shows the close control and restarts its inactivity timer.
        # ----------------------------------------------------------------------
        # Reusing one timer prevents stale callbacks from hiding a newly revealed
        # button while the pointer is still moving.
        # @return: None.
        # ----------------------------------------------------------------------
        if self._close_hide_after_id is not None:
            self.tk.after_cancel(self._close_hide_after_id)
        self._close_button.place(relx=1.0, x=-5, y=5, anchor="ne")
        self._alpha_scale.place(relx=1.0, x=-5, y=34, anchor="ne")
        self._new_color_button.place(relx=1.0, x=-28, y=38, anchor="ne")
        self._old_color_button.place(relx=1.0, x=-28, y=58, anchor="ne")
        self._source_language_menu.place(relx=1.0, x=-28, y=78, anchor="ne")
        self._target_language_menu.place(relx=1.0, x=-28, y=103, anchor="ne")
        self._close_hide_after_id = self.tk.after(1200, self._hide_close_button)
    #end def


    def _on_mouse_motion(self, _event: object) -> None:
        # Reveals the close control whenever the pointer moves over the window.
        # ----------------------------------------------------------------------
        # Motion handlers are kept on the Tk thread and do not interact with the
        # background Soniox worker.
        # @param _event: Tk mouse-motion event supplied by the binding.
        # @return: None.
        # ----------------------------------------------------------------------
        self._show_close_button()
    #end def


    def set_text(self, lines) -> None:
        # Replaces the rendered subtitle content while preserving line styles.
        # ----------------------------------------------------------------------
        # @param lines: Snapshot of subtitle line dictionaries in display order.
        # @return: None.
        # ----------------------------------------------------------------------
        # retain an empty disabled widget without rewriting it on every idle tick.
        if not lines:
            self._fit_signature = None
            if not self._rendered_visual_lines:
                return
            self._rendered_visual_lines = []
            self.text.config(state="normal")
            self.text.delete("1.0", "end")
            self.text.config(state="disabled")
            return

        # The window uses the configured number of visual rows. Fit the font and wrap using
        # actual Tk pixel measurements so the Text widget does not perform a
        # second, invisible wrap that scrolls the first row away.
        if self.settings.ui.window_borderless:
            fit_signature = tuple(
                (str(line["text"]), bool(line["last"])) for line in lines
            )
            if fit_signature == self._fit_signature:
                visual_lines = self._rendered_visual_lines
            else:
                visual_lines = self._fit_lines(lines)
                self._fit_signature = fit_signature
        else:
            visual_lines = [
                (line["text"], bool(line["last"]))
                for line in lines[-self.settings.ui.max_lines_on_screen :]
            ]

        # avoid delete/insert cycles when the subtitle snapshot is unchanged.
        if visual_lines == self._rendered_visual_lines:
            return

        self._rendered_visual_lines = visual_lines
        # enable edits only long enough to atomically replace changed content.
        self.text.config(state="normal")
        self.text.delete("1.0", "end")

        for index, (text, is_last) in enumerate(visual_lines):
            tag = ("center", "last" if is_last else "normal")
            # Do not append a newline after the final row: Tk treats the
            # trailing newline as an extra empty display row, and see("end")
            # would then scroll the first subtitle row out of the viewport.
            suffix = "\n" if index < len(visual_lines) - 1 else ""
            self.text.insert("end", text + suffix, tag)

        # scroll to the newest translation instead of leaving the viewport at
        # the first inserted line when the overlay contains multiple lines.
        self.text.see("end-1c")

        self.text.config(state="disabled")
    #end def


    def _content_size(self) -> tuple[int, int]:
        # Returns usable pixel dimensions, with a borderless-window fallback.
        self.tk.update_idletasks()
        width = self.text.winfo_width()
        height = self.text.winfo_height()
        if width < 20:
            width = self.tk.winfo_screenwidth() - 2 * self.settings.ui.window_text_padding_x
        else:
            # pack's external horizontal padding is not part of the Text widget.
            width = width - 4
        if height < 20:
            height = (
                getattr(self, "stripe_height", self.tk.winfo_screenheight())
                - 2 * self.settings.ui.window_text_padding_y
            )
        else:
            # pack's external vertical padding is already outside this widget.
            height = height - 4
        return max(40, width), max(24, height)
    #end def


    def _wrap_text(self, value: str, width: int) -> list[str]:
        # Wraps one subtitle using the current font's real pixel width.
        words = re.findall(r"\S+", value.strip())
        if not words:
            return []

        wrapped: list[str] = []
        current = ""
        for word in words:
            candidate = word if not current else f"{current} {word}"
            if current and self.display_font.measure(candidate) > width:
                wrapped.append(current)
                current = word
            else:
                current = candidate

            # Break unusually long words rather than allowing horizontal
            # clipping in the borderless overlay.
            while self.display_font.measure(current) > width and len(current) > 1:
                split = len(current) - 1
                while split > 1 and self.display_font.measure(current[:split]) > width:
                    split -= 1
                wrapped.append(current[:split])
                current = current[split:]
        if current:
            wrapped.append(current)
        return wrapped
    #end def


    def _fit_lines(self, lines) -> list[tuple[str, bool]]:
        # Selects the largest readable font that fits the configured visual rows.
        width, height = self._content_size()
        max_size = max(8, min(200, int(self.settings.ui.window_font_size) * 4))
        max_lines = max(1, self.settings.ui.max_lines_on_screen)
        selected: list[tuple[str, bool]] = []

        for size in range(max_size, 7, -1):
            self.display_font.configure(size=size)
            if self.display_font.metrics("linespace") * max_lines > height:
                continue
            candidate: list[tuple[str, bool]] = []
            for line in lines:
                for fragment in self._wrap_text(line["text"], width):
                    candidate.append((fragment, bool(line["last"])))
            if len(candidate) <= max_lines:
                selected = candidate
                break

        if not selected:
            # very long speech can still exceed the configured rows at the minimum font;
            # retain the newest visual rows rather than letting Tk scroll away
            # the first row unpredictably.
            self.display_font.configure(size=8)
            candidate = []
            for line in lines:
                for fragment in self._wrap_text(line["text"], width):
                    candidate.append((fragment, bool(line["last"])))
            selected = candidate[-max_lines:]

        return selected
    #end def


    def refresh_wraplength(self) -> None:
        # Recalculates text-widget width after the window changes size.
        # ----------------------------------------------------------------------
        # @return: None.
        # ----------------------------------------------------------------------
        # derive character capacity from available width while preserving padding.
        try:
            width = self.tk.winfo_width()
            # retain padding when converting pixel width into character capacity.
            # Width is controlled by pack/fill; wrapping is handled by
            # _fit_lines() using actual font metrics.
            self.text.configure(wrap="none")
        except Exception:
            pass
    #end def


    def run(
        self,
        subtitles: SubtitleState,
        interval_ms: int,
        stop_evt: threading.Event | None = None,
        clear_after_seconds: float = 0.0,
    ) -> None:
        # Runs the Tk event loop and periodically renders subtitle state.
        # ----------------------------------------------------------------------
        # @param subtitles: Thread-safe subtitle state read on each UI tick.
        # @param interval_ms: Delay between UI ticks in milliseconds.
        # @param stop_evt: Optional event requesting UI shutdown.
        # @param clear_after_seconds: Idle timeout for stale subtitle lines.
        # @return: None.
        # ----------------------------------------------------------------------

        def ui_tick() -> None:
            # Renders a fresh subtitle snapshot and schedules the next UI update.
            # ------------------------------------------------------------------
            # @return: None.
            # ------------------------------------------------------------------
            # close the UI when a configured termination phrase requests shutdown.
            if stop_evt is not None and stop_evt.is_set():
                self._close_window()
                return

            # clear idle subtitles before reading lines so the window reflects the
            # configured timeout without involving the Soniox worker thread.
            subtitles.clear_if_stale(clear_after_seconds)

            # update wrapping before reading lines so resize changes apply immediately.
            self.refresh_wraplength()

            # render the current thread-safe line snapshot without blocking Tk.
            self.set_text(subtitles.lines())

            # stop scheduling work after the window has been destroyed.
            if self.tk.winfo_exists():
                self.tk.after(interval_ms, ui_tick)
        #end def


        self.tk.after(interval_ms, ui_tick)
        self.tk.mainloop()
    #end def
#end class
