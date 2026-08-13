import os
import sys
import math
import shutil
import zipfile
import threading
import ctypes
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

from PyPDF2 import PdfReader, PdfWriter
import pikepdf


class PDFSplitterApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Divisor y Compresor de PDFs")
        self.root.geometry("680x580")
        self.root.minsize(600, 500)

        # Variables de estado
        self.pdf_path = tk.StringVar()
        self.output_dir = tk.StringVar()
        self.max_size_mb = tk.DoubleVar(value=14.0)
        self.is_processing = False

        self._create_widgets()

    def _create_widgets(self):
        # Frame de selección de archivo
        file_frame = ttk.LabelFrame(self.root, text=" Archivo PDF de Entrada ", padding=10)
        file_frame.pack(fill="x", padx=15, pady=5)

        ttk.Entry(file_frame, textvariable=self.pdf_path).pack(side="left", fill="x", expand=True, padx=(0, 5))
        ttk.Button(file_frame, text="Buscar PDF...", command=self._browse_pdf).pack(side="right")

        # Frame de selección de carpeta de salida
        out_frame = ttk.LabelFrame(self.root, text=" Carpeta de Salida ", padding=10)
        out_frame.pack(fill="x", padx=15, pady=5)

        ttk.Entry(out_frame, textvariable=self.output_dir).pack(side="left", fill="x", expand=True, padx=(0, 5))
        ttk.Button(out_frame, text="Buscar Carpeta...", command=self._browse_output_dir).pack(side="right")

        # Frame de configuración
        config_frame = ttk.LabelFrame(self.root, text=" Configuración ", padding=10)
        config_frame.pack(fill="x", padx=15, pady=5)

        ttk.Label(config_frame, text="Tamaño máximo por parte (MB):").pack(side="left", padx=(0, 10))
        ttk.Spinbox(
            config_frame, 
            from_=0.5, 
            to=500.0, 
            increment=0.5, 
            textvariable=self.max_size_mb, 
            width=10
        ).pack(side="left")

        # Botón de inicio
        self.btn_process = ttk.Button(self.root, text="Procesar y Dividir PDF", command=self._start_process_thread)
        self.btn_process.pack(fill="x", padx=15, pady=10)

        # Log / Consola visual
        log_frame = ttk.LabelFrame(self.root, text=" Registro de Operaciones ", padding=10)
        log_frame.pack(fill="both", expand=True, padx=15, pady=(5, 15))

        self.log_widget = scrolledtext.ScrolledText(log_frame, wrap="word", state="disabled", height=12)
        self.log_widget.pack(fill="both", expand=True)

    def _browse_pdf(self):
        file_selected = filedialog.askopenfilename(
            title="Seleccionar PDF",
            filetypes=[("Archivos PDF", "*.pdf")]
        )
        if file_selected:
            self.pdf_path.set(file_selected)
            if not self.output_dir.get():
                self.output_dir.set(os.path.dirname(file_selected))

    def _browse_output_dir(self):
        dir_selected = filedialog.askdirectory(title="Seleccionar Carpeta de Salida")
        if dir_selected:
            self.output_dir.set(dir_selected)

    def log(self, text):
        """Muestra mensajes en la consola visual de la interfaz."""
        self.log_widget.config(state="normal")
        self.log_widget.insert(tk.END, text + "\n")
        self.log_widget.see(tk.END)
        self.log_widget.config(state="disabled")

    def _clear_log(self):
        self.log_widget.config(state="normal")
        self.log_widget.delete("1.0", tk.END)
        self.log_widget.config(state="disabled")

    def _start_process_thread(self):
        if self.is_processing:
            return

        pdf_path = self.pdf_path.get().strip()
        output_dir = self.output_dir.get().strip()
        max_mb = self.max_size_mb.get()

        if not pdf_path or not os.path.exists(pdf_path):
            messagebox.showerror("Error", "Por favor selecciona un archivo PDF válido.")
            return

        if not output_dir or not os.path.exists(output_dir):
            messagebox.showerror("Error", "Por favor selecciona una carpeta de salida válida.")
            return

        if max_mb <= 0:
            messagebox.showerror("Error", "El tamaño máximo debe ser mayor que 0 MB.")
            return

        self._clear_log()
        self.is_processing = True
        self.btn_process.config(state="disabled")

        thread = threading.Thread(
            target=self._run_pdf_process, 
            args=(pdf_path, output_dir, max_mb),
            daemon=True
        )
        thread.start()

    # --- LÓGICA CORE DE PROCESAMIENTO ---

    def get_pdf_size(self, pdf_path):
        return os.path.getsize(pdf_path) / (1024 * 1024)

    def compress_pdf_lossless(self, input_path, output_path):
        original_size = self.get_pdf_size(input_path)
        if os.path.abspath(input_path) == os.path.abspath(output_path):
            self.log("⚠️ Archivo de entrada y salida son iguales, omitiendo compresión.")
            return original_size
        try:
            with pikepdf.open(input_path) as pdf:
                pdf.save(output_path, compress_streams=True, object_stream_mode=pikepdf.ObjectStreamMode.preserve)
            new_size = self.get_pdf_size(output_path)
            reduction = ((original_size - new_size) / original_size) * 100
            self.log(f"📊 Tamaño original: {original_size:.2f} MB")
            self.log(f"📊 Tamaño tras compresión: {new_size:.2f} MB")
            self.log(f"📊 Reducción: {reduction:.1f}%")
            return new_size
        except Exception as e:
            self.log(f"❌ Error en compresión: {e}")
            if os.path.abspath(input_path) != os.path.abspath(output_path):
                shutil.copy2(input_path, output_path)
            return original_size

    def calculate_parts_needed(self, compressed_size_mb, max_size_mb):
        if compressed_size_mb <= max_size_mb:
            return 1
        return math.ceil(compressed_size_mb / max_size_mb)

    def find_optimal_cut_point(self, pdf_path, start_page, total_pages, max_size_mb):
        temp_dir = os.path.join(self.output_dir.get(), "temp_opt")
        os.makedirs(temp_dir, exist_ok=True)
        reader = PdfReader(pdf_path)
        best_end_page = start_page
        best_size = 0

        self.log(f"   🔍 Buscando combinación óptima desde página {start_page + 1}...")

        for test_end_page in range(start_page + 1, total_pages + 1):
            writer = PdfWriter()
            writer.append(reader, pages=(start_page, test_end_page))

            temp_path = os.path.join(temp_dir, "test_part.pdf")
            with open(temp_path, 'wb') as f:
                writer.write(f)

            part_size = self.get_pdf_size(temp_path)

            if part_size <= max_size_mb:
                best_end_page = test_end_page
                best_size = part_size
                if part_size >= max_size_mb * 0.95:
                    self.log(f"   ✅ Corte óptimo: págs {start_page+1}-{test_end_page} ({part_size:.2f} MB)")
                    break
            else:
                if best_end_page > start_page:
                    self.log(f"   ✅ Mejor combinación: págs {start_page+1}-{best_end_page} ({best_size:.2f} MB)")
                else:
                    best_end_page = start_page + 1
                    writer_forced = PdfWriter()
                    writer_forced.append(reader, pages=(start_page, start_page + 1))
                    temp_forced_path = os.path.join(temp_dir, "forced_test.pdf")
                    with open(temp_forced_path, 'wb') as f:
                        writer_forced.write(f)
                    forced_size = self.get_pdf_size(temp_forced_path)
                    self.log(f"   ⚠️ Forzando corte mínimo (1 pág): pág {start_page+1} ({forced_size:.2f} MB)")
                break
        else:
            if best_end_page > start_page:
                self.log(f"   ✅ Última combinación: págs {start_page+1}-{best_end_page} ({best_size:.2f} MB)")

        shutil.rmtree(temp_dir, ignore_errors=True)
        return best_end_page, best_size

    def split_pdf_by_max_size(self, pdf_path, output_dir, num_parts, max_size_mb):
        if not os.path.exists(pdf_path):
            self.log(f"❌ Error: No se encuentra {pdf_path}")
            return [], 0

        reader = PdfReader(pdf_path)
        total_pages = len(reader.pages)
        self.log(f"📊 Total de páginas: {total_pages}")

        base_name = os.path.splitext(os.path.basename(pdf_path))[0]
        if base_name.endswith('_comprimido'):
            base_name = base_name.replace('_comprimido', '')

        output_files = []
        current_page = 0
        actual_parts = 0

        while current_page < total_pages:
            actual_parts += 1
            self.log(f"\n📦 Procesando parte {actual_parts}...")

            end_page, part_size = self.find_optimal_cut_point(
                pdf_path, current_page, total_pages, max_size_mb
            )

            writer = PdfWriter()
            writer.append(reader, pages=(current_page, end_page))

            output_filename = f"{base_name}_parte{actual_parts}.pdf"
            output_path = os.path.join(output_dir, output_filename)
            with open(output_path, 'wb') as output_file:
                writer.write(output_file)

            final_size = self.get_pdf_size(output_path)
            status = "✅ DENTRO DEL LÍMITE" if final_size <= max_size_mb else "⚠️ EXCEDE LÍMITE"
            self.log(f"   {status} Parte {actual_parts}: págs {current_page+1}-{end_page}, tamaño: {final_size:.2f} MB")

            output_files.append(output_path)
            current_page = end_page

            if current_page >= total_pages:
                break

        return output_files, actual_parts

    def _run_pdf_process(self, pdf_path, output_dir, max_size_mb):
        try:
            self.log("🚀 Iniciando procesamiento del PDF...")
            original_size = self.get_pdf_size(pdf_path)
            self.log(f"📄 Archivo: {os.path.basename(pdf_path)} ({original_size:.2f} MB)")

            temp_dir = os.path.join(output_dir, "pdf_temp_process")
            os.makedirs(temp_dir, exist_ok=True)
            base_name = os.path.splitext(os.path.basename(pdf_path))[0]

            self.log("\n🔄 Aplicando compresión lossless...")
            compressed_path = os.path.join(temp_dir, f"{base_name}_comprimido.pdf")
            final_size = self.compress_pdf_lossless(pdf_path, compressed_path)

            parts_needed_estimate = self.calculate_parts_needed(final_size, max_size_mb)

            if parts_needed_estimate == 1 and final_size <= max_size_mb:
                self.log(f"\n✅ {final_size:.2f} MB ≤ {max_size_mb} MB → El archivo ya cumple con el tamaño máximo.")
                final_filename = f"{base_name}_comprimido.pdf"
                final_path = os.path.join(output_dir, final_filename)
                shutil.copy2(compressed_path, final_path)
                self.log(f"🎉 Guardado en: {final_path}")
            else:
                self.log(f"\n⚠️ {final_size:.2f} MB > {max_size_mb} MB → Dividiendo en partes...")
                parts, actual_parts = self.split_pdf_by_max_size(compressed_path, output_dir, parts_needed_estimate, max_size_mb)

                zip_filename = os.path.join(output_dir, f"{base_name}_partes.zip")
                with zipfile.ZipFile(zip_filename, 'w') as zipf:
                    for part in parts:
                        zipf.write(part, os.path.basename(part))

                self.log(f"\n📦 Archivo ZIP empaquetado: {zip_filename}")

            shutil.rmtree(temp_dir, ignore_errors=True)
            self.log("\n✅ ¡Proceso completado exitosamente!")
            messagebox.showinfo("Éxito", "El PDF ha sido procesado y dividido correctamente.")

        except Exception as e:
            self.log(f"\n❌ Error durante el procesamiento: {str(e)}")
            messagebox.showerror("Error", f"Ocurrió un error inesperado:\n{str(e)}")
        finally:
            self.is_processing = False
            self.btn_process.config(state="normal")


if __name__ == "__main__":
    # Solución DPI para corregir texto borroso en monitores High-DPI en Windows
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

    root = tk.Tk()
    app = PDFSplitterApp(root)
    root.mainloop()
