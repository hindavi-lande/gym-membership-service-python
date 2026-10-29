from flask import Blueprint, jsonify, request

from app.services import member_service

members_bp = Blueprint("members", __name__, url_prefix="/api")


@members_bp.get("/members")
def list_members():
    members = member_service.list_members()
    return jsonify([member.to_dict() for member in members])


@members_bp.post("/members")
def create_member():
    member = member_service.create_member(_json_body())
    return jsonify(member.to_dict()), 201


@members_bp.get("/members/<int:member_id>")
def get_member(member_id):
    member = member_service.get_member(member_id)
    return jsonify(member.to_dict())


@members_bp.put("/members/<int:member_id>")
def update_member(member_id):
    member = member_service.update_member(member_id, _json_body())
    return jsonify(member.to_dict())


@members_bp.post("/members/<int:member_id>/renew")
def renew_member(member_id):
    member = member_service.renew_member(member_id)
    return jsonify(member.to_dict())


@members_bp.delete("/members/<int:member_id>")
def delete_member(member_id):
    member_service.delete_member(member_id)
    return "", 204


def _json_body():
    body = request.get_json(silent=True)
    return {} if body is None else body
