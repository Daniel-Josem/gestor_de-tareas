from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory, jsonify
import sqlite3, os
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from flask_login import LoginManager, login_user, login_required, logout_user, current_user, UserMixin

app = Flask(__name__)
app.secret_key = 'tu_clave_secreta'
DATABASE = 'usuarios.db'

UPLOAD_FOLDER = 'archivos_tareas'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    # -- CREACIÓN TABLAS --
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            nombre_usuario TEXT UNIQUE NOT NULL,
            curso TEXT NOT NULL,
            documento TEXT UNIQUE NOT NULL,
            correo TEXT UNIQUE NOT NULL,
            contrasena TEXT NOT NULL,
            rol TEXT DEFAULT 'rol_usuario',
            fecha_registro DATETIME DEFAULT CURRENT_TIMESTAMP,
            activo INTEGER DEFAULT 1,
            tema TEXT DEFAULT 'claro',
            idioma TEXT DEFAULT 'es',
            notificaciones INTEGER DEFAULT 1
        );
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tareas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            titulo TEXT NOT NULL,
            descripcion TEXT,
            fecha_vencimiento DATE,
            prioridad TEXT,
            estado TEXT DEFAULT 'pendiente',
            id_proyecto INTEGER,
            id_usuario_asignado INTEGER,
            ruta_archivo TEXT,
            curso_destino TEXT,
            FOREIGN KEY (id_usuario_asignado) REFERENCES usuarios(id) ON DELETE SET NULL
        );
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS proyectos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            descripcion TEXT,
            fecha_inicio DATE,
            fecha_fin DATE,
            estado TEXT DEFAULT 'activo',
            id_usuario_creador INTEGER,
            FOREIGN KEY (id_usuario_creador) REFERENCES usuarios(id) ON DELETE SET NULL
        );
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS notificaciones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mensaje TEXT NOT NULL,
            leido INTEGER DEFAULT 0,
            fecha DATETIME DEFAULT CURRENT_TIMESTAMP,
            id_usuario INTEGER,
            FOREIGN KEY (id_usuario) REFERENCES usuarios(id) ON DELETE CASCADE
        );
    ''')

    # -- Usuarios admin y profesor por defecto --
    cursor.execute('SELECT COUNT(*) FROM usuarios WHERE nombre_usuario = "admin"')
    if cursor.fetchone()[0] == 0:
        cursor.execute('''
            INSERT INTO usuarios (nombre, nombre_usuario, curso, documento, correo, contrasena, rol)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', ('Administrador', 'admin', 'N/A', '00000000', 'admin@example.com',
              generate_password_hash('admin123'), 'rol_administrador'))

    cursor.execute('SELECT COUNT(*) FROM usuarios WHERE nombre_usuario = "profesor1"')
    if cursor.fetchone()[0] == 0:
        cursor.execute('''
            INSERT INTO usuarios (nombre, nombre_usuario, curso, documento, correo, contrasena, rol)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', ('Profesor Juan', 'profesor1', 'Matemáticas', '12345678', 'profesor1@example.com',
              generate_password_hash('profesor123'), 'rol_profesor'))

    conn.commit()
    conn.close()

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

class Usuario(UserMixin):
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

@login_manager.user_loader
def load_user(user_id):
    conn = get_db_connection()
    fila = conn.execute('SELECT * FROM usuarios WHERE id = ?', (user_id,)).fetchone()
    conn.close()
    return Usuario(**dict(fila)) if fila else None

@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        usuario = request.form['nombre_usuario']
        contrasena = request.form['contrasena']
        conn = get_db_connection()
        fila = conn.execute('SELECT * FROM usuarios WHERE nombre_usuario = ?', (usuario,)).fetchone()
        conn.close()
        if fila and check_password_hash(fila['contrasena'], contrasena) and fila['activo']:
            login_user(Usuario(**dict(fila)))
            # Redirige según rol
            return redirect(url_for(fila['rol'].replace('rol_', '')))
        flash('Usuario o contraseña incorrectos')
    return render_template('login.html')

@app.route('/crear_usuario', methods=['GET', 'POST'])
def crear_usuario():
    if request.method == 'POST':
        datos = {k: request.form[k] for k in ['nombre', 'nombre_usuario', 'curso', 'documento', 'correo']}
        datos['contrasena'] = generate_password_hash(request.form['contrasena'])
        datos['rol'] = request.form.get('rol', 'rol_usuario')
        conn = get_db_connection()
        try:
            conn.execute('''
                INSERT INTO usuarios (nombre, nombre_usuario, curso, documento, correo, contrasena, rol)
                VALUES (:nombre, :nombre_usuario, :curso, :documento, :correo, :contrasena, :rol)
            ''', datos)
            conn.commit()
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash('El nombre de usuario, documento o correo ya existe')
        finally:
            conn.close()
    return render_template('crear_usuario.html')

# --- Rutas para profesor ---

@app.route('/profesor')
@login_required
def profesor():
    if current_user.rol != 'rol_profesor':
        return redirect(url_for('index'))

    estado = request.args.get('estado')
    curso_filtro = request.args.get('curso')

    conn = get_db_connection()

    # Cursos disponibles para filtros (de estudiantes activos)
    cursos = conn.execute(
        'SELECT DISTINCT curso FROM usuarios WHERE rol = "rol_usuario" AND activo = 1'
    ).fetchall()

    # Cursos a los que el profesor tiene tareas asignadas
    resultado = conn.execute(
        'SELECT DISTINCT curso_destino FROM tareas WHERE id_usuario_asignado = ?',
        (current_user.id,)
    ).fetchall()
    lista_cursos = [fila['curso_destino'] for fila in resultado]

    if not lista_cursos:
        tareas = []
    else:
        query = f'''
            SELECT * FROM tareas
            WHERE curso_destino IN ({','.join(['?'] * len(lista_cursos))})
            AND id_usuario_asignado = ?
        '''
        args = lista_cursos + [current_user.id]

        if estado in ['pendiente', 'completada']:
            query += ' AND estado = ?'
            args.append(estado)

        if curso_filtro:
            query += ' AND curso_destino = ?'
            args.append(curso_filtro)

        tareas = conn.execute(query, args).fetchall()

    conn.close()

    return render_template(
        'profesor.html',
        cursos=cursos,
        tareas=tareas,
        estado=estado,
        curso_filtro=curso_filtro
    )




@app.route('/api/cursos', methods=['GET'])
@login_required
def api_cursos():
    if current_user.rol != 'rol_profesor':
        return jsonify({'error': 'No autorizado'}), 403

    conn = get_db_connection()
    filas = conn.execute(
        'SELECT DISTINCT curso FROM usuarios WHERE rol = "rol_usuario" AND activo = 1'
    ).fetchall()
    conn.close()

    # Ahora devolvemos la lista con clave 'curso'
    lista = [{'curso': fila['curso']} for fila in filas]
    print("DEBUG /api/cursos ->", lista)
    return jsonify(lista)



@app.route('/editar_tarea/<int:id>', methods=['POST'], endpoint='editar_tarea_profesor')
@login_required
def editar_tarea(id):
    if current_user.rol != 'rol_profesor':
        return jsonify({'error': 'No autorizado'}), 403

    conn = get_db_connection()
    tarea = conn.execute('SELECT * FROM tareas WHERE id = ? AND id_usuario_asignado = ?', (id, current_user.id)).fetchone()

    if not tarea:
        conn.close()
        return jsonify({'error': 'Tarea no encontrada o sin permiso para editarla'}), 404

    titulo = request.form['titulo']
    descripcion = request.form['descripcion']
    fecha_vencimiento = request.form.get('fecha_vencimiento')
    prioridad = request.form.get('prioridad')
    estado = request.form.get('estado')
    curso_destino = request.form['curso_destino']
    archivo = request.files.get('archivo')
    ruta_archivo = tarea['ruta_archivo']

    if archivo and archivo.filename:
        # Borrar archivo viejo si existe
        if ruta_archivo and os.path.exists(ruta_archivo):
            os.remove(ruta_archivo)
        filename = secure_filename(archivo.filename)
        ruta_archivo = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        archivo.save(ruta_archivo)

    conn.execute('''
        UPDATE tareas SET titulo=?, descripcion=?, fecha_vencimiento=?, prioridad=?, estado=?, curso_destino=?, ruta_archivo=?
        WHERE id=?
    ''', (titulo, descripcion, fecha_vencimiento, prioridad, estado, curso_destino, ruta_archivo, id))
    conn.commit()
    conn.close()

    flash('Tarea actualizada')
    return redirect(url_for('profesor'))

@app.route('/eliminar_tarea/<int:id>', methods=['POST'])
@login_required
def eliminar_tarea(id):
    if current_user.rol != 'rol_profesor':
        return jsonify({'error': 'No autorizado'}), 403

    conn = get_db_connection()
    tarea = conn.execute('SELECT * FROM tareas WHERE id = ? AND id_usuario_asignado = ?', (id, current_user.id)).fetchone()

    if not tarea:
        conn.close()
        return jsonify({'error': 'Tarea no encontrada o sin permiso para eliminarla'}), 404

    ruta_archivo = tarea['ruta_archivo']
    if ruta_archivo and os.path.exists(ruta_archivo):
        os.remove(ruta_archivo)

    conn.execute('DELETE FROM tareas WHERE id = ?', (id,))
    conn.commit()
    conn.close()

    flash('Tarea eliminada')
    return redirect(url_for('profesor'))

@app.route('/crear_tarea_profesor', methods=['POST'])
@login_required
def crear_tarea_profesor():
    if current_user.rol != 'rol_profesor':
        return redirect(url_for('index'))

    # Recolectamos los datos del formulario
    titulo = request.form['titulo']
    descripcion = request.form['descripcion']
    curso_destino = request.form['curso_destino']
    fecha_vencimiento = request.form.get('fecha_vencimiento')
    prioridad = request.form.get('prioridad')
    estado = request.form.get('estado', 'pendiente')
    archivo = request.files.get('archivo')

    ruta_archivo = ''
    if archivo and archivo.filename:
        filename = secure_filename(archivo.filename)
        ruta_archivo = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        archivo.save(ruta_archivo)

    conn = get_db_connection()

    # Obtenemos TODOS los IDs de estudiantes activos del curso destino
    filas_estudiantes = conn.execute(
        'SELECT id FROM usuarios WHERE rol = "rol_usuario" AND activo = 1 AND curso = ?',
        (curso_destino,)
    ).fetchall()
    ids_estudiantes = [fila['id'] for fila in filas_estudiantes]

    # Si no hay alumnos en ese curso, devolvemos un mensaje y abortamos
    if not ids_estudiantes:
        conn.close()
        flash(f'No hay estudiantes activos en el curso "{curso_destino}". La tarea no fue enviada.')
        return redirect(url_for('profesor'))

    # Insertamos una tarea para el profesor
    conn.execute(
        '''
        INSERT INTO tareas (
            titulo, descripcion, fecha_vencimiento,
            prioridad, estado, curso_destino,
            ruta_archivo, id_usuario_asignado
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''',
        (titulo, descripcion, fecha_vencimiento, prioridad,
         estado, curso_destino, ruta_archivo, current_user.id)
    )

    # Para cada estudiante, insertamos una tarea y una notificación
    for alumno_id in ids_estudiantes:
        conn.execute(
            '''
            INSERT INTO tareas (
                titulo, descripcion, fecha_vencimiento,
                prioridad, estado, curso_destino,
                ruta_archivo, id_usuario_asignado
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (titulo, descripcion, fecha_vencimiento, prioridad,
             estado, curso_destino, ruta_archivo, alumno_id)
        )

        mensaje = f'Se ha creado una nueva tarea: "{titulo}"'
        conn.execute(
            'INSERT INTO notificaciones (mensaje, id_usuario) VALUES (?, ?)',
            (mensaje, alumno_id)
        )

    conn.commit()
    conn.close()

    flash('Tarea creada correctamente y enviada a todos los estudiantes del curso.')
    return redirect(url_for('profesor'))



@app.route('/notificaciones')
@login_required
def ver_notificaciones():
    conn = get_db_connection()
    notifs = conn.execute('SELECT * FROM notificaciones WHERE id_usuario = ? ORDER BY fecha DESC', (current_user.id,)).fetchall()
    conn.close()
    return render_template('notificaciones.html', notificaciones=notifs)

@app.route('/marcar_leido/<int:id>', methods=['POST'])
@login_required
def marcar_notificacion_leida(id):
    conn = get_db_connection()
    conn.execute('UPDATE notificaciones SET leido = 1 WHERE id = ? AND id_usuario = ?', (id, current_user.id))
    conn.commit()
    conn.close()
    return jsonify({'status': 'ok'})

@app.route('/descargar_archivo/<path:filename>')
@login_required
def descargar_archivo(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename, as_attachment=True)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

if __name__ == '__main__':
    init_db()
    app.run(debug=True)
