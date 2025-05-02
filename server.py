import os
from sqlalchemy import *
from sqlalchemy.pool import NullPool
from flask import Flask, request, render_template, g, redirect, Response, session, flash, url_for
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from decimal import Decimal

tmpl_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates')
app = Flask(__name__, template_folder=tmpl_dir)
app.secret_key = '747fb74ea2ef418a154b8af724709538'

# Database URI setup
DB_USER = "rl3431"
DB_PASSWORD = "rl3431"
DB_SERVER = "w4111.cisxo09blonu.us-east-1.rds.amazonaws.com"
DATABASEURI = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_SERVER}/w4111"

engine = create_engine(DATABASEURI)

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in first')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.before_request
def before_request():
    try:
        g.conn = engine.connect()
        g.conn.execute(text("SET search_path TO rl3431"))
    except:
        print("Error connecting to database")
        import traceback; traceback.print_exc()
        g.conn = None

@app.teardown_request
def teardown_request(exception):
    try:
        g.conn.close()
    except Exception as e:
        pass

@app.route('/')
@login_required
def index():
    try:
        # Get user details
        user_query = text("""
            SELECT 
                u.user_id,
                u.email,
                u.phone_number,
                u.username,
                a.address_id,
                a.street_number,
                a.street_name,
                a.zip_code,
                a.city,
                a.state
            FROM users u
            JOIN addresses a ON u.address_id = a.address_id
            WHERE u.user_id = :user_id
        """)
        
        user_info = g.conn.execute(user_query, 
                                 {'user_id': session['user_id']}).fetchone()

        # Get user purchase history
        purchases_query = text("""
            SELECT 
                o.order_id,
                o.order_date,
                a.title as artwork_title,
                o.quantity,
                p.amount,
                p.payment_method,
                u.username as seller_name
            FROM orders o
            JOIN artwork_prints_uploaded a ON o.artwork_id = a.artwork_id
            JOIN payments_made p ON o.order_id = p.order_id
            JOIN users u ON o.seller_id = u.user_id
            WHERE o.user_id = :user_id
            ORDER BY o.order_date DESC
        """)
        
        purchase_history = g.conn.execute(purchases_query, 
                                        {'user_id': session['user_id']}).fetchall()

        return render_template(
            'profile.html',
            user=user_info,
            purchases=purchase_history
        )

    except Exception as e:
        print(f"Error loading profile: {e}")
        flash('Error loading profile')
        return redirect(url_for('artworks'))

@app.route('/update-profile', methods=['POST'])
@login_required
def update_profile():
    try:
        
        user_count_query = text("""
            SELECT COUNT(*) 
            FROM users
            WHERE (username = :username
              OR phone_number = :phone_number
              OR email = :email)
              AND user_id != :user_id
        """)
        
        count = g.conn.execute(user_count_query, {
            'username': request.form['username'],
            'phone_number': request.form['phone_number'],
            'email': request.form['email'],
            'user_id': session['user_id']
        }).scalar()
        
        if count > 0:
            flash('Username, phone number, or email already exists')
            return redirect(url_for('index'))

        # Update user details
        user_query = text("""
            UPDATE users 
            SET email = :email,
                phone_number = :phone_number,
                username = :username
            WHERE user_id = :user_id
        """)
        
        g.conn.execute(user_query, {
            'email': request.form['email'],
            'phone_number': request.form['phone_number'],
            'username': request.form['username'],
            'user_id': session['user_id']
        })

        address_query = text("""
            UPDATE addresses 
            SET street_number = :street_number,
                street_name = :street_name,
                zip_code = :zip_code,
                city = :city,
                state = :state
            WHERE address_id = :address_id
        """)
        
        g.conn.execute(address_query, {
            'street_number': request.form['street_number'],
            'street_name': request.form['street_name'],
            'zip_code': request.form['zip_code'],
            'city': request.form['city'],
            'state': request.form['state'],
            'address_id': request.form['address_id']
        })

        g.conn.commit()
        session['username'] = request.form['username']
        flash('Profile updated successfully!')
        
    except Exception as e:
        print(f"Error updating profile: {e}")
        g.conn.rollback()
        flash('Error updating profile')
    
    return redirect(url_for('index'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        # Get user and hashed password from database
        query = text("""
            SELECT user_id, username, password 
            FROM users 
            WHERE username = :username
        """)
        
        result = g.conn.execute(query, {'username': username}).fetchone()
        print("===============================",result,"=================")
        if result and check_password_hash(result[2], password):
            # Store user info in session
            session['user_id'] = result[0]
            session['username'] = result[1]
            flash('Login successful!')
            return redirect(url_for('index'))
        else:
            flash('Invalid username or password')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out')
    return redirect(url_for('login'))

@app.route('/artworks')
@login_required
def artworks():
    try:
        category_query = text("""
            SELECT category_id, title 
            FROM categories 
            ORDER BY title
        """)
        categories = g.conn.execute(category_query).fetchall()

        selected_category = request.args.get('category_id')
        sort_by = request.args.get('sort', 'price_low')
        search_query = request.args.get('search', '').strip()

        query = """
            SELECT 
                a.artwork_id,
                a.image_url,
                a.title,
                a.description,
                a.price,
                u.username as artist_name,
                c.title as category_name
            FROM artwork_prints_uploaded a
            JOIN users u ON a.user_id = u.user_id
            JOIN categories c ON a.category_id = c.category_id
            WHERE 1=1
        """
        params = {}

        # Category filter
        if selected_category:
            query += " AND a.category_id = :category_id"
            params['category_id'] = selected_category

        # Search filter
        if search_query:
            query += """ AND (
                LOWER(a.title) LIKE LOWER(:search)
                OR LOWER(a.description) LIKE LOWER(:search)
                OR LOWER(u.username) LIKE LOWER(:search)
            )"""
            params['search'] = f'%{search_query}%'

        # Sort
        if sort_by == 'price_high':
            query += " ORDER BY a.price DESC"
        else:  # price_low
            query += " ORDER BY a.price ASC"

        # Execute query
        artworks = g.conn.execute(text(query), params).fetchall()

        return render_template(
            'artworks.html',
            artworks=artworks,
            categories=categories,
            selected_category=selected_category,
            sort_by=sort_by,
            search_query=search_query
        )
    except Exception as e:
        print(f"Error: {e}")
        flash('An error occurred while loading artworks')
        return redirect(url_for('index'))

@app.route('/artwork/<int:artwork_id>')
@login_required
def artwork_detail(artwork_id):
    try:
        # Get artwork details including artist information
        artwork_query = text("""
            SELECT 
                a.artwork_id,
                a.image_url,
                a.title,
                a.description,
                a.price,
                u.username as artist_name,
                u.email as artist_email,
                u.user_id as artist_id,
                c.title as category_name
            FROM artwork_prints_uploaded a
            JOIN users u ON a.user_id = u.user_id
            JOIN categories c ON a.category_id = c.category_id
            WHERE a.artwork_id = :artwork_id
        """)
        
        artwork = g.conn.execute(artwork_query, {'artwork_id': artwork_id}).fetchone()
        
        if artwork is None:
            flash('Artwork not found')
            return redirect(url_for('artworks'))

        # Get user address
        address_query = text("""
            SELECT 
                address_id,
                street_number,
                street_name,
                zip_code,
                city,
                state
            FROM addresses
            WHERE address_id = (
                SELECT address_id 
                FROM users 
                WHERE user_id = :user_id
            )
        """)
        
        user_address = g.conn.execute(address_query, 
                                    {'user_id': session['user_id']}).fetchone()

        # Get other artworks by the same user
        artist_works_query = text("""
            SELECT 
                artwork_id,
                title,
                image_url,
                price
            FROM artwork_prints_uploaded
            WHERE user_id = :artist_id
            AND artwork_id != :artwork_id
            LIMIT 4
        """)
        
        artist_other_works = g.conn.execute(artist_works_query, {
            'artist_id': artwork.artist_id,
            'artwork_id': artwork_id
        }).fetchall()
            
        return render_template('artwork_detail.html', 
                             artwork=artwork, 
                             user_address=user_address,
                             other_works=artist_other_works)
    except Exception as e:
        print(f"Error: {e}")
        flash('An error occurred while loading the artwork')
        return redirect(url_for('artworks'))

@app.route('/purchase/<int:artwork_id>', methods=['POST'])
@login_required
def purchase_artwork(artwork_id):
    try:
        # Get the next IDs
        next_address_id = g.conn.execute(text("SELECT COALESCE(MAX(address_id), 0) + 1 FROM addresses")).scalar()
        next_order_id = g.conn.execute(text("SELECT COALESCE(MAX(order_id), 0) + 1 FROM orders")).scalar()
        next_payment_id = g.conn.execute(text("SELECT COALESCE(MAX(payment_id), 0) + 1 FROM payments_made")).scalar()

        # Get artwork info (seller_id and price)
        artwork_query = text("SELECT user_id, price FROM artwork_prints_uploaded WHERE artwork_id = :artwork_id")
        artwork_info = g.conn.execute(artwork_query, {'artwork_id': artwork_id}).fetchone()
        
        seller_id = artwork_info[0]
        artwork_price = artwork_info[1]
        quantity = int(request.form.get('quantity', 1))
        total_amount = artwork_price * quantity

        # Check user is not buying own artwork
        if seller_id == session['user_id']:
            flash('Unfortunately, you cannot purchase your own artwork!')
            return redirect(url_for('artwork_detail', artwork_id=artwork_id))
        
        # Create new address
        address_query = text("""
            INSERT INTO addresses (
                address_id, street_number, street_name, zip_code, city, state
            ) VALUES (
                :address_id, :street_number, :street_name, :zip_code, :city, :state
            )
        """)
        
        g.conn.execute(address_query, {
            'address_id': next_address_id,
            'street_number': request.form['street_number'],
            'street_name': request.form['street_name'],
            'zip_code': request.form['zip_code'],
            'city': request.form['city'],
            'state': request.form['state']
        })
        
        # Create order
        order_query = text("""
            INSERT INTO orders (
                order_id, quantity, order_date, user_id, seller_id, artwork_id, address_id
            ) VALUES (
                :order_id, :quantity, CURRENT_DATE, :user_id, :seller_id, 
                :artwork_id, :address_id
            )
        """)
        
        g.conn.execute(order_query, {
            'order_id': next_order_id,
            'quantity': quantity,
            'user_id': session['user_id'],
            'seller_id': seller_id,
            'artwork_id': artwork_id,
            'address_id': next_address_id
        })
        
        # Create payment
        payment_query = text("""
            INSERT INTO payments_made (
                payment_id, order_id, payment_method, amount, payment_date, user_id
            ) VALUES (
                :payment_id, :order_id, :payment_method, :amount, CURRENT_DATE, :user_id
            )
        """)
        
        g.conn.execute(payment_query, {
            'payment_id': next_payment_id,
            'order_id': next_order_id,
            'payment_method': request.form['payment_method'],
            'amount': total_amount,
            'user_id': session['user_id']
        })
        
        verify_queries = [
            (text("SELECT * FROM orders WHERE order_id = :id"), 
             {'id': next_order_id}, "Order"),
            (text("SELECT * FROM payments_made WHERE payment_id = :id"), 
             {'id': next_payment_id}, "Payment"),
            (text("SELECT * FROM addresses WHERE address_id = :id"), 
             {'id': next_address_id}, "Address")
        ]
        print("\nVerifying Records:")
        for query, params, record_type in verify_queries:
            result = g.conn.execute(query, params).fetchone()
            print(f"{record_type} exists: {result}")

        g.conn.commit()
        flash(f'Purchase successful! Order #{next_order_id} has been created.', 'success')
        return redirect(url_for('artworks'))
        
    except Exception as e:
        print(f"Error during purchase: {e}")
        g.conn.rollback()
        flash(f'Error occurred during purchase: {str(e)}', 'error')
        return redirect(url_for('artwork_detail', artwork_id=artwork_id))
        
@app.route('/my-artworks')
@login_required
def my_artworks():
    try:
        # Get all artworks user is selling
        artworks_query = text("""
            SELECT 
                a.artwork_id,
                a.title,
                a.description,
                a.price,
                a.image_url,
                c.title as category_name,
                (SELECT COUNT(*) FROM orders WHERE artwork_id = a.artwork_id) as times_sold,
                (SELECT COALESCE(SUM(amount), 0) 
                 FROM orders o 
                 JOIN payments_made p ON o.order_id = p.order_id 
                 WHERE o.artwork_id = a.artwork_id) as total_earned
            FROM artwork_prints_uploaded a
            JOIN categories c ON a.category_id = c.category_id
            WHERE a.user_id = :user_id
            ORDER BY a.artwork_id DESC
        """)
        
        artworks = g.conn.execute(artworks_query, 
                                {'user_id': session['user_id']}).fetchall()

        # Get total earnings
        earnings_query = text("""
            SELECT COALESCE(SUM(p.amount), 0) as total_earnings,
                   COUNT(DISTINCT o.order_id) as total_orders
            FROM orders o
            JOIN payments_made p ON o.order_id = p.order_id
            WHERE o.seller_id = :user_id
        """)
        
        earnings_info = g.conn.execute(earnings_query, 
                                     {'user_id': session['user_id']}).fetchone()

        # Get orders for user's artworks
        orders_query = text("""
            SELECT 
                o.order_id,
                o.order_date,
                o.quantity,
                a.title as artwork_title,
                p.amount,
                p.payment_method,
                u.username as buyer_name,
                addr.city,
                addr.state
            FROM orders o
            JOIN artwork_prints_uploaded a ON o.artwork_id = a.artwork_id
            JOIN payments_made p ON o.order_id = p.order_id
            JOIN users u ON o.user_id = u.user_id
            JOIN addresses addr ON o.address_id = addr.address_id
            WHERE o.seller_id = :user_id
            ORDER BY o.order_date DESC
        """)
        
        orders = g.conn.execute(orders_query, 
                              {'user_id': session['user_id']}).fetchall()

        # Get categories for new artwork
        categories_query = text("SELECT category_id, title FROM categories ORDER BY title")
        categories = g.conn.execute(categories_query).fetchall()

        return render_template(
            'my_artworks.html',
            artworks=artworks,
            total_earnings=earnings_info.total_earnings,
            total_orders=earnings_info.total_orders,
            orders=orders,
            categories=categories
        )

    except Exception as e:
        print(f"Error in my-artworks: {e}")
        flash('An error occurred while loading your artworks')
        return redirect(url_for('index'))

@app.route('/create-artwork', methods=['POST'])
@login_required
def create_artwork():
    try:
        # Get next artwork_id
        next_id_query = text("SELECT COALESCE(MAX(artwork_id), 0) + 1 FROM artwork_prints_uploaded")
        next_artwork_id = g.conn.execute(next_id_query).scalar()

        # Create new artwork
        artwork_query = text("""
            INSERT INTO artwork_prints_uploaded (
                artwork_id, image_url, title, description, 
                price, user_id, category_id
            ) VALUES (
                :artwork_id, :image_url, :title, :description, 
                :price, :user_id, :category_id
            )
        """)

        g.conn.execute(artwork_query, {
            'artwork_id': next_artwork_id,
            'image_url': request.form['image_url'],
            'title': request.form['title'],
            'description': request.form['description'],
            'price': float(request.form['price']),
            'user_id': session['user_id'],
            'category_id': int(request.form['category_id'])
        })

        g.conn.commit()
        flash('Artwork created successfully!')
        
    except Exception as e:
        print(f"Error creating artwork: {e}")
        flash('Error creating artwork')
        g.conn.rollback()
    
    return redirect(url_for('my_artworks'))


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        try:
            # Get next user_id and address_id
            next_user_id = g.conn.execute(text("SELECT COALESCE(MAX(user_id), 0) + 1 FROM users")).scalar()
            next_address_id = g.conn.execute(text("SELECT COALESCE(MAX(address_id), 0) + 1 FROM addresses")).scalar()
            
            # Create address
            address_query = text("""
                INSERT INTO addresses (
                    address_id, street_number, street_name, zip_code, city, state
                ) VALUES (
                    :address_id, :street_number, :street_name, :zip_code, :city, :state
                )
            """)
            
            g.conn.execute(address_query, {
                'address_id': next_address_id,
                'street_number': request.form['street_number'],
                'street_name': request.form['street_name'],
                'zip_code': request.form['zip_code'],
                'city': request.form['city'],
                'state': request.form['state']
            })

            # Create user
            user_query = text("""
                INSERT INTO users (
                    user_id, email, phone_number, username, password, address_id
                ) VALUES (
                    :user_id, :email, :phone_number, :username, :password, :address_id
                )
            """)
            
            hashed_password = generate_password_hash(request.form['password'])
            
            g.conn.execute(user_query, {
                'user_id': next_user_id,
                'email': request.form['email'],
                'phone_number': request.form['phone_number'],
                'username': request.form['username'],
                'password': hashed_password,
                'address_id': next_address_id
            })

            g.conn.commit()
            flash('Account created successfully! Please login.')
            return redirect(url_for('login'))
            
        except Exception as e:
            print(f"Error during registration: {e}")
            g.conn.rollback()
            flash('Error creating account. Please try again.')
            return redirect(url_for('register'))
    
    return render_template('register.html')
  

@app.route('/artwork/<int:artwork_id>/edit')
@login_required
def edit_artwork(artwork_id):
    try:
        # Get artwork details
        artwork_query = text("""
            SELECT * FROM artwork_prints_uploaded 
            WHERE artwork_id = :artwork_id AND user_id = :user_id
        """)
        
        artwork = g.conn.execute(artwork_query, {
            'artwork_id': artwork_id,
            'user_id': session['user_id']
        }).fetchone()
        
        if artwork is None:
            flash('Artwork not found or you do not have permission to edit it')
            return redirect(url_for('my_artworks'))

        # Get categories
        categories_query = text("SELECT category_id, title FROM categories ORDER BY title")
        categories = g.conn.execute(categories_query).fetchall()

        return render_template('edit_artwork.html', artwork=artwork, categories=categories)

    except Exception as e:
        print(f"Error loading artwork: {e}")
        flash('An error occurred while loading the artwork')
        return redirect(url_for('my_artworks'))

@app.route('/artwork/<int:artwork_id>/update', methods=['POST'])
@login_required
def update_artwork(artwork_id):
    try:
        # Verify ownership
        verify_query = text("""
            SELECT 1 FROM artwork_prints_uploaded 
            WHERE artwork_id = :artwork_id AND user_id = :user_id
        """)
        
        result = g.conn.execute(verify_query, {
            'artwork_id': artwork_id,
            'user_id': session['user_id']
        }).fetchone()
        
        if not result:
            flash('You do not have permission to edit this artwork')
            return redirect(url_for('my_artworks'))

        # Update artwork
        update_query = text("""
            UPDATE artwork_prints_uploaded 
            SET title = :title,
                description = :description,
                price = :price,
                image_url = :image_url,
                category_id = :category_id
            WHERE artwork_id = :artwork_id AND user_id = :user_id
        """)
        
        g.conn.execute(update_query, {
            'title': request.form['title'],
            'description': request.form['description'],
            'price': float(request.form['price']),
            'image_url': request.form['image_url'],
            'category_id': int(request.form['category_id']),
            'artwork_id': artwork_id,
            'user_id': session['user_id']
        })

        g.conn.commit()
        flash('Artwork updated successfully!')
        
    except Exception as e:
        print(f"Error updating artwork: {e}")
        g.conn.rollback()
        flash('Error updating artwork')
    
    return redirect(url_for('my_artworks'))



if __name__ == "__main__":
    import click

    @click.command()
    @click.option('--debug', is_flag=True)
    @click.option('--threaded', is_flag=True)
    @click.argument('HOST', default='0.0.0.0')
    @click.argument('PORT', default=8111, type=int)
    def run(debug, threaded, host, port):
        HOST, PORT = host, port
        print(f"running on {HOST}:{PORT}")
        app.run(host=HOST, port=PORT, debug=debug, threaded=threaded)

    run()