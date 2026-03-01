from flask_bcrypt import Bcrypt
bcrypt = Bcrypt()

hash_134 = bcrypt.generate_password_hash("134").decode("utf-8")
print(hash_134)
