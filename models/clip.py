from datetime import datetime
from models.user import db

class ClipFeedback(db.Model):
	id = db.Column(db.Integer, primary_key=True)
	clip_id = db.Column(db.String(120), nullable=False, index=True)
	vote = db.Column(db.Integer, nullable=False)  # +1 or -1
	features = db.Column(db.JSON, nullable=True)
	# optional: who sent the feedback (user or anonymous session)
	user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True, index=True)
	session_id = db.Column(db.String(128), nullable=True, index=True)
	created_at = db.Column(db.DateTime, default=datetime.utcnow)

	def __repr__(self):
		return f"<ClipFeedback clip_id={self.clip_id} vote={self.vote} id={self.id}>"
