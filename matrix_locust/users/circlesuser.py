#!/bin/env python3

###########################################################
#
# tbd update
#
# circlesuser.py - The MatrixChatUser class
# -- Acts like a Matrix chat user
#
# Created: 2022-08-05
# Author: Charles V Wright <cvwright@futo.org>
# Copyright: 2022 FUTO Holdings Inc
# License: Apache License version 2.0
#
# The MatrixChatUser class extends MatrixUser to add some
# basic chatroom user behaviors.

# Upon login to the homeserver, this user spawns a second
# "background" Greenlet to act as the user's client's
# background sync task.  The "background" Greenlet sleeps and
# calls /sync in an infinite loop, and it uses the responses
# to /sync to populate the user's local understanding of the
# world state.
#
# Meanwhile, the user's main "foreground" Greenlet does the
# things that a Locust User normally does, sleeping and then
# picking a random @task to execute.  The available set of
# @tasks includes: accepting invites to join rooms, sending
# m.text messages, sending reactions, and paginating backward
# in a room.
#
###########################################################

import csv
import os
import sys
import glob
import random
import resource

import json
import logging

import gevent
from locust import task, tag, constant, between, TaskSet
from locust import events
from locust.runners import MasterRunner, WorkerRunner

from matrixuser import MatrixUser
from nio import MatrixRoom, RoomMessageText
from nio.responses import RoomSendError, RoomMessagesError, SyncError, LoginError

from typing import Optional

from nio.api import (
    RoomPreset,
    RoomVisibility,
    _FilterT,
)

from nio import ChangeJoinRulesBuilder

from typing import (
    Any,
    Dict,
    List,
    Tuple,
)

import time

# Preflight ###############################################

@events.init.add_listener
def on_locust_init(environment, **_kwargs):
    # Increase resource limits to prevent OS running out of descriptors
    try:
        resource.setrlimit(resource.RLIMIT_NOFILE, (999999, 999999))
    except ValueError as e:
        logging.warning(f"Failed to increase the resource limit: {e}")

    # Multi-worker
    if isinstance(environment.runner, WorkerRunner):
        print(f"Registered 'load_users' handler on {environment.runner.client_id}")
        environment.runner.register_message("load_users", CirclesUser.load_users)
    # Single-worker
    elif not isinstance(environment.runner, WorkerRunner) and not isinstance(environment.runner, MasterRunner):
        # Open our list of users
        # CirclesUser.worker_users = csv.DictReader(open("users.csv"))
        print("Single worker, loading users.csv...")
        CirclesUser.worker_users = iter(csv.DictReader(open("users.csv")))

###########################################################



class CirclesUser(MatrixUser):
    wait_time = constant(0)
    worker_id = None
    worker_users = []

    @staticmethod
    def load_users(environment, msg, **_kwargs):
        CirclesUser.worker_users = iter(msg.data)
        CirclesUser.worker_id = environment.runner.client_id
        logging.info("Worker [%s] Received %s users", environment.runner.client_id, len(msg.data))

    @tag("registration")
    @task
    def registration(self):
        # Multiple locust users re-use the same class instance, so need to reset the state
        self.reset_client()

        # Sleep between room creation to emulate Android Circles app behavior
        #client_sleep = True
        client_sleep = False

        # Load the next user
        try:
            user = next(CirclesUser.worker_users)
        except StopIteration:
            # We can't shut down the worker until all users are registered, so return
            # early to stop this individual co-routine
            gevent.sleep(999999)
            return

        self.matrix_client.user = user["username"]
        self.matrix_client.password = user["password"]

        if self.matrix_client.user is None or self.matrix_client.password is None:
            logging.error("Couldn't get username/password. Skipping...")
            return

        # Register the account via UIA
        self.matrix_client.register_uia()
        # exit()

        # self.matrix_client.login_uia()

        # Setup user profile
        # * Displayname
        # * Avatar URL
        self.matrix_client.set_displayname(self.matrix_client.user)
        self.matrix_client.set_avatar("")


        private_rule = ChangeJoinRulesBuilder("private")

        # # spec says to use knock rule instead?
        # invite_rule = ChangeJoinRulesBuilder("invite")

        # re-add space content to tagging? think it uses canonical at least...
        space_content = {
            "canonical": True,
            "via": [
                "example.org",
                "other.example.org"
            ]
        }


        # temp rules dicts
        power_levels_space_dict = {
            "events_default": 100,
        }

        power_levels_dict = {
            "invite": 50,
        }


         # emulating android app with 1s delay
        # gevent.sleep(1)
        # time.sleep(1)

        # Create Circles spaces hierarchy
        root_room_id = self.create_room("Circles", None, None, None, "m.space",
                                        "org.futo.space.root", None,
                                        power_levels_space_dict, private_rule.as_dict())
        if client_sleep:
            gevent.sleep(1)

        circles_room_id = self.create_room("My Circles", None, None, None, "m.space",
                                           "org.futo.space.circles", root_room_id,
                                           power_levels_space_dict, private_rule.as_dict())
        if client_sleep:
            gevent.sleep(1)

        groups_room_id = self.create_room("My Groups", None, None, None, "m.space",
                                          "org.futo.space.groups", root_room_id,
                                          power_levels_space_dict, private_rule.as_dict())
        if client_sleep:
            gevent.sleep(1)

        photos_room_id = self.create_room("My Photo Galleries", None, None, None, "m.space",
                                          "org.futo.space.photos", root_room_id,
                                          power_levels_space_dict, private_rule.as_dict())
        if client_sleep:
            gevent.sleep(1)


        # "My People" and "User display name" spaces not created in android app?

        # Create sub-space rooms
        self.create_room("Photos", None, None, None, "org.futo.social.gallery",
                         "org.futo.social.gallery", photos_room_id,
                         power_levels_dict, private_rule.as_dict())
        if client_sleep:
            gevent.sleep(1)

        self.create_circle_with_timeline("Friends", None, circles_room_id)
        if client_sleep:
            gevent.sleep(1)

        self.create_circle_with_timeline("Family", None, circles_room_id)
        if client_sleep:
            gevent.sleep(1)

        self.create_circle_with_timeline("Community", None, circles_room_id)
        if client_sleep:
            gevent.sleep(1)

        # Set room names and avatars


    # modeled from android app
    def create_circle_with_timeline(self, name: str, icon_uri: str, space_parent_id: str) -> str:
        # temp defines
        power_levels_dict = {
            "invite": 50,
        }

        # spec says to use knock rule instead?
        invite_rule = ChangeJoinRulesBuilder("invite")

        circle_room_id = self.create_room(name, None, icon_uri, None, "m.space",
                         "org.futo.social.circle", space_parent_id, power_levels_dict,
                         invite_rule.as_dict())

        self.create_room(name, None, icon_uri, None, "org.futo.social.timeline",
                         "org.futo.social.timeline", circle_room_id,
                         power_levels_dict, invite_rule.as_dict())

        return circle_room_id


    # modeled from android app
    def create_room(self,
                    name: str,
                    topic: str,
                    icon_uri: str,
                    invite_ids: List[str],
                    room_type: str,
                    tag: str,
                    space_parent_id: str,
                    power_levels: Dict[str, int],
                    join_rules: Dict[str, Any],
                    ) -> str:
        # temp dict constants
        power_levels_dict = {
            "invite": 50,
        }

        is_space = False

        # Other custom room types other than 'm.space' currently not supported
        if room_type == "m.space":
            is_space = True

        request = self.matrix_client.room_create(
            visibility=RoomVisibility.private,
            name=name,
            topic=topic,
            preset=RoomPreset.private_chat,
            power_level_override=power_levels,
            space=is_space
        )

        self.matrix_client.room_set_tags(request.room_id, tag)
        self.matrix_client.room_put_state(request.room_id, "m.room.join_rules", join_rules)

        if not(space_parent_id is None):
            self.matrix_client.room_put_state(request.room_id, "m.space.parent", {}, space_parent_id)
            self.matrix_client.room_put_state(space_parent_id, "m.space.child", {}, request.room_id)
        # todo: enable room encryption?

        return request.room_id



        # power levels dict not added to room builder yet...
        # object Admin : Role(100)
        # object Moderator : Role(50)
        # object Default : Role(0)

        #   "content": {
        #     "ban": 50,
        #     "events": {
        #     "m.room.name": 100,
        #     "m.room.power_levels": 100
        #     },
        #     "events_default": 0,
        #     "invite": 50,
        #     "kick": 50,
        #     "notifications": {
        #     "room": 20
        #     },
        #     "redact": 50,
        #     "state_default": 50,
        #     "users": {
        #     "@example:localhost": 100
        #     },
        #     "users_default": 0
        # },

