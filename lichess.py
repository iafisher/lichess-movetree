#!/usr/bin/env python3
"""An interactive script to play with the lichess API.

Docs for the API can be found at https://github.com/ornicar/lila#http-api
"""
import requests
import time
import math
import json
import os
import argparse
import readline
from operator import itemgetter, attrgetter
from collections import Counter, namedtuple


API_ENDPOINT = 'https://lichess.org/api/'
CACHE_DIR = '.cache'


class Profile:
    def __init__(self, username, *, build=False, **build_kwargs):
        self.username = username
        self.real_name = ''
        self.bullet_rating = 0
        self.bullet_games = 0
        self.blitz_rating = 0
        self.blitz_games = 0
        self.classical_rating = 0
        self.classical_games = 0
        self.all_games = []
        self.openings = Counter()
        self.first_moves_as_white = Counter()
        self.responses_to_e4 = Counter()
        self.responses_to_d4 = Counter()
        if build is True:
            self.build(**build_kwargs)

    def build(self, verbose=True):
        data = call_lichess_api(API_ENDPOINT + 'user/' + self.username, verbose=verbose)
        # Get profile information.
        json_profile = data.get('profile')
        if json_profile:
            first_name = json_profile.get('firstName', '')
            last_name = json_profile.get('lastName', '')
            if first_name and last_name:
                self.real_name = first_name + ' ' + last_name
            elif first_name or last_name:
                self.real_name = first_name + last_name
        # Get rating information.
        json_perf = data['perfs']
        json_bullet = json_perf.get('bullet')
        if json_bullet:
            self.bullet_rating = json_bullet['rating']
            self.bullet_games = json_bullet['games']
        json_blitz = json_perf.get('blitz')
        if json_blitz:
            self.blitz_rating = json_blitz['rating']
            self.blitz_games = json_blitz['games']
        json_classical = json_perf.get('classical')
        if json_classical:
            self.classical_rating = json_classical['rating']
            self.classical_games = json_classical['games']
        # Get game information.
        # Call API for the first time to see how many pages of results there will be.
        url = API_ENDPOINT + 'user/' + self.username + '/games'
        data = call_lichess_api(url, verbose=verbose, params={'nb': 0})
        total_results = data.get('nbResults', 0)
        total_pages = math.ceil(total_results / 100)
        page = 1
        payload = {'nb': 100, 'page': page, 'with_opening': 1, 'with_moves': 1}
        while page <= total_pages:
            data = call_lichess_api(url, verbose=verbose, params=payload)
            if verbose is True:
                print('Fetched page {} of {}'.format(page, total_pages))
            for game_obj in data['currentPageResults']:
                self._process_game(game_obj)
            page += 1
            payload['page'] = page

    def _process_game(self, game_json):
        if game_json['variant'] != 'standard' or not game_json['moves']:
            return
        try:
            self.openings[game_json['opening']['name']] += 1
        except KeyError:
            pass
        moves_list = game_json['moves'].split(' ')
        first_move = moves_list[0]
        if game_json['players']['white']['userId'] == self.username:
            self.first_moves_as_white[first_move] += 1
            if game_json['status'] in ('mate', 'resign', 'outoftime'):
                self.all_games.append( (moves_list, 'white', game_json['winner']) )
            elif game_json['status'] in ('stalemate', 'draw'):
                self.all_games.append( (moves_list, 'white', None) )
        else:
            if game_json['status'] in ('mate', 'resign', 'outoftime'):
                self.all_games.append( (moves_list, 'black', game_json['winner']) )
            elif game_json['status'] in ('stalemate', 'draw'):
                self.all_games.append( (moves_list, 'black', None) )
            if first_move == 'e4':
                self.responses_to_e4[moves_list[1]] += 1
            elif first_move == 'd4':
                self.responses_to_d4[moves_list[1]] += 1

    def filter_games(self, moves_so_far, you=True):
        return [game for game in self.all_games if game[0][:len(moves_so_far)] == moves_so_far]

    def prettyprint(self):
        if self.real_name:
            print('=== {0.username} ({0.real_name}) ===\n'.format(self))
        else:
            print('=== {0.username} ===\n'.format(self))
        if self.bullet_games > 0:
            print('Bullet rating: {0.bullet_rating} over {0.bullet_games} game(s)'.format(self))
        if self.blitz_games > 0:
            print('Blitz rating: {0.blitz_rating} over {0.blitz_games} game(s)'.format(self))
        if self.classical_games > 0:
            print('Classical rating: {0.classical_rating} over {0.classical_games} game(s)'.format(self))
        if self.bullet_games > 0 or self.blitz_games > 0 or self.classical_games > 0:
            print()

        print('Favorite openings')
        for i, (opening, count) in enumerate(self.openings.most_common(3), start=1):
            print('  {}. {} ({} game{})'.format(i, opening, count, '' if count == 1 else 's'))
        print()

        print('Favorite responses to 1. e4')
        for i, (move, count) in enumerate(self.responses_to_e4.most_common(3), start=1):
            print('  {}. {} ({} game{})'.format(i, move, count, '' if count == 1 else 's'))
        print()

        print('Favorite responses to 1. d4')
        for i, (move, count) in enumerate(self.responses_to_d4.most_common(3), start=1):
            print('  {}. {} ({} game{})'.format(i, move, count, '' if count == 1 else 's'))
        print()


last_api_call = 0
def call_lichess_api(url, use_cache=True, verbose=False, **kwargs):
    """Call the Lichess API, taking care not to send more than one API call per second."""
    global last_api_call
    fpath = os.path.join(CACHE_DIR, url_to_fpath(url, **kwargs))
    if use_cache and os.path.exists(fpath):
        with open(fpath, 'r') as fsock:
            data = json.load(fsock)
        return data
    else:
        waiting_time = (last_api_call + 1.5) - time.time()
        if waiting_time > 0:
            time.sleep(waiting_time)
        r = requests.get(url, **kwargs)
        while r.status_code == 429:
            if verbose is True:
                print('Sleeping')
            time.sleep(61)
            r = requests.get(url, **kwargs)
        last_api_call = time.time()
        data = r.json()
        if not os.path.exists(CACHE_DIR):
            os.mkdir(CACHE_DIR)
        with open(os.path.join(CACHE_DIR, url_to_fpath(url, **kwargs)), 'w') as fsock:
            json.dump(data, fsock)
        return data


def url_to_fpath(url, **kwargs):
    # Strip off the common prefix.
    url = url[len(API_ENDPOINT):]
    url = url.replace('/', '_')
    params_dict = kwargs.get('params')
    if params_dict:
        sorted_dict = sorted(params_dict.items(), key=itemgetter(0))
        params_str = '_'.join(key + '=' + str(val) for key, val in sorted_dict)
        return url + '_' + params_str + '.json'
    else:
        return url + '.json'


MoveTree = namedtuple('MoveTree', ['parent', 'children', 'wins', 'draws', 'losses', 'stack'])


class MoveTree:
    def __init__(self):
        self.parent = None
        self.children = {}
        self.wins = 0
        self.draws = 0
        self.losses = 0
        self.total = 0
        self.stack = []

    @classmethod
    def from_parent(cls, parent, move):
        ret = cls()
        ret.parent = parent
        ret.stack = parent.stack + [move]
        return ret

    def build_next_level(self, games):
        if len(self.children) > 0:
            # The next level has already been built.
            return
        for moves, color, result in games:
            move = moves[len(self.stack)]
            try:
                node = self.children[move]
            except KeyError:
                node = MoveTree.from_parent(self, move)
                self.children[move] = node
            node.update_results(result)

    def update_results(self, result):
        self.total += 1
        if result is None:
            self.draws += 1
        elif (result == 'white' and len(self.stack) % 2 == 1) or \
             (result == 'black' and len(self.stack) % 2 == 0):
            self.wins += 1
        else:
            self.losses += 1


# I may switch this to use a more robust opening book, like the one in the python-chess package.
OPENING_NAMES = {
    ('e4', 'c5'): 'Sicilian Defense',
    ('e4', 'c6'): 'Caro-Kann Defense',
    ('e4', 'e6'): 'French Defense',
    ('e4', 'd5'): 'Scandinavian Defense',
    ('e4', 'Nf6'): "Alekhine's Defense",
    ('e4', 'e5', 'Nc3'): 'Vienna Game',
    ('e4', 'e5', 'd4'): 'Center Game',
    ('e4', 'e5', 'f4'): "King's Gambit",
    ('e4', 'e5', 'Nf3', 'Nf6'): "Petrov's Defense",
    ('e4', 'e5', 'Nf3', 'f5'): 'Latvian Gambit',
    ('e4', 'e5', 'Nf3', 'd6'): 'Philidor Defense',
    ('e4', 'e5', 'Nf3', 'Nc6', 'Bb5'): 'Ruy Lopez',
    ('e4', 'e5', 'Nf3', 'Nc6', 'Bc4'): 'Italian Game',
    ('e4', 'e5', 'Nf3', 'Nc6', 'Nc3'): "Three Knight's Game",
    ('e4', 'e5', 'Nf3', 'Nc6', 'd4'): 'Scotch Game',
    ('d4', 'Nf6'): 'Indian Defense',
    ('d4', 'd5', 'c4'): "Queen's Gambit",
    ('c4',): 'English Opening',
}


class MoveExplorer:
    """Explore the moves from all the games of a given Lichess user."""

    def __init__(self, username, color, **profile_kwargs):
        self.profile = Profile(username, build=True, **profile_kwargs)
        self._init_everything_else(color)

    def _init_everything_else(self, color):
        self.color = color
        self.your_turn = (color == 'white')
        self.opening = None
        # The ply at which the opening was determined. Used for backtracking.
        self.opening_ply = 0
        self.tree = MoveTree()
        self.games = [g for g in self.profile.all_games if g[1] == self.color]
        self.tree.build_next_level(self.games)

    def backtrack(self):
        if self.tree.parent is not None:
            self.tree = self.tree.parent
            self.your_turn = not self.your_turn
            self.games = [g for g in self.profile.all_games
                                  if g[0][:len(self.tree.stack)] == self.tree.stack and \
                                     g[1] == self.color]
            if len(self.tree.stack) <= self.opening_ply:
                self.opening = OPENING_NAMES.get(tuple(self.tree.stack))
                if self.opening is None:
                    self.opening_ply = 0

    def advance(self, move):
        try:
            self.tree = self.tree.children[move]
        except KeyError:
            raise ValueError from None
        else:
            self.your_turn = not self.your_turn
            self.games = [g for g in self.games if g[0][:len(self.tree.stack)] == self.tree.stack]
            if self.opening is None:
                self.opening = OPENING_NAMES.get(tuple(self.tree.stack))
                self.opening_ply = len(self.tree.stack)
            self.tree.build_next_level(self.games)

    def flip(self):
        self._init_everything_else('white' if color == 'black' else 'black')

    def moves_so_far(self):
        return self.tree.stack

    def available_moves(self):
        return sorted(self.tree.children.items(), key=lambda p: p[1].total, reverse=True)


def format_pl(string, n):
    return string.format(n, '' if n == 1 else 's')



if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('username', nargs='?')
    parser.add_argument('--clear-cache', action='store_true', help='clear the Lichess API cache')
    parser.add_argument('--verbose', action='store_true')
    args = parser.parse_args()
    if args.clear_cache is True:
        for fpath in os.listdir(CACHE_DIR):
            os.remove(os.path.join(CACHE_DIR, fpath))
    if args.username is not None:
        username = args.username
    else:
        username = input('Please enter your Lichess username: ').strip()
    print('\nLoading user data...\n')
    explorer = MoveExplorer(username, 'white', verbose=args.verbose)
    while True:
        if explorer.your_turn is True:
            print(format_pl('\nYOUR MOVES (from {} game{})', len(explorer.games)))
        else:
            print(format_pl("\nYOUR OPPONENTS' MOVES (from {} game{})", len(explorer.games)))
        for move, node in explorer.available_moves():
            wins = node.wins / node.total
            draws = node.draws / node.total
            losses = node.losses / node.total
            # I believe that Ng3xe5+ (7 chars) is the longest possible chess move in strict
            # algebraic notation.
            print('{:7}'.format(move), end='')
            if not explorer.your_turn:
                wins, losses = losses, wins
            print(' (you won {:7,.2%}, drew {:7,.2%},'.format(wins, draws), end='')
            print(' and lost {:7,.2%}'.format(losses), end='')
            print(format_pl(', from {} game{})', node.total))
        print()
        # Print the moves so far.
        moves_so_far = explorer.moves_so_far()
        if moves_so_far:
            for i, move in enumerate(moves_so_far, start=1):
                if i % 2 == 1:
                    print('{}. {}'.format(i, move), end='')
                else:
                    print(' {}  '.format(move), end='')
            # Print the name of the opening.
            if explorer.opening is not None:
                if len(moves_so_far) % 2 == 1:
                    print('  ', end='')
                print('({})'.format(explorer.opening))
            else:
                print()
        response = input('{}>>> '.format(explorer.color)).strip()
        if response.lower() == 'quit':
            break
        elif response.lower() == 'back':
            explorer.backtrack()
        elif response.lower() == 'flip':
            explorer.flip()
        else:
            try:
                explorer.advance(response)
            except ValueError:
                print('No games found.\n')
