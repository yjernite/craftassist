"""
Copyright (c) Facebook, Inc. and its affiliates.
"""

import unittest
from unittest.mock import Mock

from build_utils import to_relative_pos
from base_agent.dialogue_objects import AwaitResponse
from fake_agent import FakeAgent
from mc_memory_nodes import ObjectNode
from typing import List, Sequence, Dict
from util import XYZ, Block, IDM
from utils import Player, Pos, Look, Item
from world import World, Opt, flat_ground_generator


class BaseCraftassistTestCase(unittest.TestCase):
    def setUp(self, agent_opts=None):
        spec = {
            "players": [Player(42, "SPEAKER", Pos(5, 63, 5), Look(270, 0), Item(0, 0))],
            "mobs": [],
            "ground_generator": flat_ground_generator,
            "agent": {"pos": (0, 63, 0)},
            "coord_shift": (-16, 54, -16),
        }
        world_opts = Opt()
        world_opts.sl = 32
        self.world = World(world_opts, spec)
        self.agent = FakeAgent(self.world, opts=agent_opts)

        # More helpful error message to encourage test writers to use self.set_looking_at()
        self.agent.get_player_line_of_sight = Mock(
            side_effect=NotImplementedError(
                "Cannot call into C++ function in this unit test. "
                + "Call self.set_looking_at() to set the return value"
            )
        )

        self.speaker = self.agent.get_other_players()[0].name
        self.agent.perceive()

        # Combinable actions to be used in test cases
        self.possible_actions = {
            "destroy_speaker_look": {
                "action_type": "DESTROY",
                "reference_object": {"location": {"location_type": "SPEAKER_LOOK"}},
            },
            "copy_speaker_look_to_agent_pos": {
                "action_type": "BUILD",
                "reference_object": {"location": {"location_type": "SPEAKER_LOOK"}},
                "location": {"location_type": "AGENT_POS"},
            },
            "build_small_sphere": {
                "action_type": "BUILD",
                "schematic": {"has_name": "sphere", "has_size": "small"},
            },
            "build_1x1x1_cube": {
                "action_type": "BUILD",
                "schematic": {"has_name": "cube", "has_size": "1 x 1 x 1"},
            },
            "move_speaker_pos": {
                "action_type": "MOVE",
                "location": {"location_type": "SPEAKER_POS"},
            },
            "build_diamond": {"action_type": "BUILD", "schematic": {"has_name": "diamond"}},
            "build_gold_cube": {
                "action_type": "BUILD",
                "schematic": {"has_block_type": "gold", "has_name": "cube"},
            },
            "fill_all_holes_speaker_look": {
                "action_type": "FILL",
                "location": {"location_type": "SPEAKER_LOOK"},
                "repeat": {"repeat_key": "ALL"},
            },
            "go_to_tree": {
                "action_type": "MOVE",
                "location": {
                    "location_type": "REFERENCE_OBJECT",
                    "reference_object": {"has_name": "tree"},
                },
            },
            "build_square_height_1": {
                "action_type": "BUILD",
                "schematic": {"has_name": "square", "has_height": "1"},
            },
            "stop": {"action_type": "STOP"},
            "fill_speaker_look": {
                "action_type": "FILL",
                "location": {"location_type": "SPEAKER_LOOK"},
            },
            "fill_speaker_look_gold": {
                "action_type": "FILL",
                "has_block_type": "gold",
                "location": {"location_type": "SPEAKER_LOOK"},
            },
        }

    def handle_logical_form(
        self, d, chatstr: str = "", answer: str = None, stop_on_chat=False, max_steps=10000
    ) -> Dict[XYZ, IDM]:
        """Handle a logical form and call self.flush()

        If "answer" is specified and a question is asked by the agent, respond
        with this string.

        If "stop_on_chat" is specified, stop iterating if the agent says anything
        """
        dummy_chat = "TEST {}".format(d)
        self.add_incoming_chat(dummy_chat, self.speaker)
        self.agent.set_logical_form(d, dummy_chat, self.speaker)
        changes = self.flush(max_steps, stop_on_chat=stop_on_chat)
        if len(self.agent.dialogue_manager.dialogue_stack) != 0 and answer is not None:
            self.add_incoming_chat(answer, self.speaker)
            changes.update(self.flush(max_steps, stop_on_chat=stop_on_chat))
        return changes

    def flush(self, max_steps=10000, stop_on_chat=False) -> Dict[XYZ, IDM]:
        """Run the agant's step until task and dialogue stacks are empty

        If "stop_on_chat" is specified, stop iterating if the agent says anything

        Return the set of blocks that were changed.
        """
        if stop_on_chat:
            self.agent.clear_outgoing_chats()

        world_before = self.agent.world.blocks_to_dict()

        for _ in range(max_steps):
            self.agent.step()
            if self.agent_should_stop(stop_on_chat):
                break

        # get changes
        world_after = self.world.blocks_to_dict()
        changes = dict(set(world_after.items()) - set(world_before.items()))
        changes.update({k: (0, 0) for k in set(world_before.keys()) - set(world_after.keys())})
        return changes

    def agent_should_stop(self, stop_on_chat=False):
        stop = False
        if (
            len(self.agent.dialogue_manager.dialogue_stack) == 0
            and not self.agent.memory.task_stack_peek()
        ):
            stop = True
        # stuck waiting for answer?
        if (
            isinstance(self.agent.dialogue_manager.dialogue_stack.peek(), AwaitResponse)
            and not self.agent.dialogue_manager.dialogue_stack.peek().finished
        ):
            stop = True
        if stop_on_chat and self.agent.get_last_outgoing_chat():
            stop = True
        return stop

    def set_looking_at(self, xyz: XYZ):
        """Set the return value for C++ call to get_player_line_of_sight"""
        self.agent.get_player_line_of_sight = Mock(return_value=Pos(*xyz))

    def set_blocks(self, xyzbms: List[Block], origin: XYZ = (0, 0, 0)):
        self.agent.set_blocks(xyzbms, origin)

    def add_object(self, xyzbms: List[Block], origin: XYZ = (0, 0, 0)) -> ObjectNode:
        return self.agent.add_object(xyzbms, origin)

    def add_incoming_chat(self, chat: str, speaker_name: str):
        """Add a chat to memory as if it was just spoken by SPEAKER"""
        self.world.chat_log.append("<" + speaker_name + ">" + " " + chat)

    #        self.agent.memory.add_chat(self.agent.memory.get_player_by_name(self.speaker).memid, chat)

    def assert_schematics_equal(self, a, b):
        """Check equality between two list[(xyz, idm)] schematics

        N.B. this compares the shapes and idms, but ignores absolute position offsets.
        """
        a, _ = to_relative_pos(a)
        b, _ = to_relative_pos(b)
        self.assertEqual(set(a), set(b))

    def get_idm_at_locs(self, xyzs: Sequence[XYZ]) -> Dict[XYZ, IDM]:
        return self.world.get_idm_at_locs(xyzs)

    def last_outgoing_chat(self) -> str:
        return self.agent.get_last_outgoing_chat()

    def get_speaker_pos(self) -> XYZ:
        return self.agent.memory.get_player_by_name(self.speaker).pos
