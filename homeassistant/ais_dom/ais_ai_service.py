"""
Support for functionality to have conversations with AI-Speaker.

"""
import asyncio
import logging
import re
import warnings
import json
import voluptuous as vol
import datetime
import requests
from homeassistant import core
from homeassistant.loader import bind_hass
from homeassistant.const import (
    ATTR_ENTITY_ID, SERVICE_TURN_OFF,
    SERVICE_TURN_ON, ATTR_UNIT_OF_MEASUREMENT)
from homeassistant.helpers import intent, config_validation as cv
from homeassistant.ais_dom import ais_cloud
from homeassistant.ais_dom import ais_global
import homeassistant.components.mqtt as mqtt
aisCloudWS = ais_cloud.AisCloudWS()

REQUIREMENTS = ['fuzzywuzzy==0.15.1', 'babel']
# DEPENDENCIES = ['http']

ATTR_TEXT = 'text'
DOMAIN = 'ais_ai_service'
G_HTTP_REST_SERVICE_BASE_URL = 'http://{}:8122'

REGEX_TURN_COMMAND = re.compile(r'turn (?P<name>(?: |\w)+) (?P<command>\w+)')

SERVICE_PROCESS_SCHEMA = vol.Schema({
    vol.Required(ATTR_TEXT): cv.string,
})

CONFIG_SCHEMA = vol.Schema({DOMAIN: vol.Schema({
    vol.Optional('intents'): vol.Schema({
        cv.string: vol.All(cv.ensure_list, [cv.string])
    })
})}, extra=vol.ALLOW_EXTRA)

INTENT_GET_TIME = 'AisGetTime'
INTENT_GET_DATE = 'AisGetDate'
INTENT_TURN_ON = 'AisTurnOn'
INTENT_TURN_OFF = 'AisTurnOff'
INTENT_STATUS = 'AisStatusInfo'
INTENT_PLAY_RADIO = 'AisPlayRadio'
INTENT_PLAY_PODCAST = 'AisPlayPodcast'
INTENT_PLAY_YT_MUSIC = 'AisPlayYtMusic'
INTENT_ASK_QUESTION = 'AisAskQuestion'
INTENT_CHANGE_CONTEXT = 'AisChangeContext'
INTENT_GET_WEATHER = 'AisGetWeather'
INTENT_GET_WEATHER_48 = 'AisGetWeather48'
INTENT_LAMPS_ON = 'AisLampsOn'
INTENT_LAMPS_OFF = 'AisLampsOff'
INTENT_SWITCHES_ON = 'AisSwitchesOn'
INTENT_SWITCHES_OFF = 'AisSwitchesOff'
REGEX_TYPE = type(re.compile(''))

_LOGGER = logging.getLogger(__name__)
GROUP_VIEWS = ['Twój Dom', 'Audio', 'Ustawienia', 'Pomoc']
CURR_GROUP_VIEW = None
# group entities in each group view, see main_ais_groups.yaml
GROUP_ENTITIES = []
CURR_GROUP = None
CURR_ENTITIE = None
CURR_BUTTON_CODE = None
CURR_ENTITIE_POSITION = None
ALL_SWITCHES = ["input_boolean", "automation", "switch", "light",
                "media_player", "script"]
GLOBAL_TTS_TEXT = None


def get_tts_text():
    return GLOBAL_TTS_TEXT


def isSwitch(entity_id):
    global ALL_SWITCHES
    # problem with startswith and tuple of strings
    for s in ALL_SWITCHES:
        if entity_id.startswith(s):
            return True
    return False


@core.callback
@bind_hass
def async_register(hass, intent_type, utterances):
    """Register an intent.
    Registrations don't require conversations to be loaded. They will become
    active once the conversation component is loaded.
    """
    intents = hass.data.get(DOMAIN)

    if intents is None:
        intents = hass.data[DOMAIN] = {}

    conf = intents.get(intent_type)

    if conf is None:
        conf = intents[intent_type] = []

    for utterance in utterances:
        if isinstance(utterance, REGEX_TYPE):
            conf.append(utterance)
        else:
            conf.append(_create_matcher(utterance))


def get_next(arra, curr):
    _first = None
    _curr = None
    _next = None
    for a in arra:
        # ignore empy option
        if a != ais_global.G_EMPTY_OPTION:
            if _curr is not None and _next is None:
                _next = a
            if _first is None:
                _first = a
            if (curr == a):
                _curr = a
    if _next is not None:
        return _next
    else:
        return _first


def get_prev(arra, curr):
    _last = None
    _curr = None
    _prev = None
    for a in arra:
        # ignore empy option
        if a != ais_global.G_EMPTY_OPTION:
            _last = a
            if (curr == a):
                _curr = a
            if _curr is None:
                _prev = a
    if _prev is not None:
        return _prev
    else:
        return _last


# Group views: Dom -> Audio -> Ustawienia -> Pomoc
def get_curr_group_view():
    if CURR_GROUP_VIEW is None:
        return GROUP_VIEWS[0]
    return CURR_GROUP_VIEW


def say_curr_group_view(hass):
    _say_it(hass, get_curr_group_view())


def set_curr_group_view():
    # set focus on current menu group view
    global CURR_GROUP_VIEW
    global CURR_GROUP
    global CURR_ENTITIE
    global CURR_ENTITIE_POSITION
    CURR_GROUP = None
    CURR_ENTITIE = None
    CURR_ENTITIE_POSITION = None
    CURR_GROUP_VIEW = get_curr_group_view()


def set_next_group_view():
    # set focus on next menu group view
    global CURR_GROUP_VIEW
    CURR_GROUP_VIEW = get_next(GROUP_VIEWS, get_curr_group_view())
    # to reset
    set_curr_group_view()


def set_prev_group_view():
    # set focus on prev menu group view
    global CURR_GROUP_VIEW
    CURR_GROUP_VIEW = get_prev(GROUP_VIEWS, get_curr_group_view())
    # to reset
    set_curr_group_view()


# Groups in Groups views
def get_curr_group():
    global CURR_GROUP
    if CURR_GROUP is None:
        # take the first one from Group view
        for group in GROUP_ENTITIES:
            if group['remote_group_view'] == get_curr_group_view():
                CURR_GROUP = group
    return CURR_GROUP


def get_curr_group_idx():
    idx = 0
    for group in GROUP_ENTITIES:
        if group['entity_id'] == get_curr_group()['entity_id']:
            return idx
        idx += 1
    return idx


def say_curr_group(hass):
    _say_it(hass, get_curr_group()['friendly_name'])


def set_curr_group(hass, group):
    # set focus on current menu group view
    global CURR_GROUP_VIEW
    global CURR_GROUP
    global CURR_ENTITIE
    global CURR_ENTITIE_POSITION
    CURR_ENTITIE = None
    CURR_ENTITIE_POSITION = None
    if group is None:
        CURR_GROUP = get_curr_group()
        hass.states.async_set(
            'binary_sensor.selected_entity',
            CURR_GROUP['entity_id'])
    else:
        CURR_GROUP_VIEW = group['remote_group_view']
        CURR_GROUP = group


def set_next_group(hass):
    # set focus on next group in focused view
    global CURR_GROUP
    first_group_in_view = None
    curr_group_in_view = None
    next_group_in_view = None
    selected_group = None
    for group in GROUP_ENTITIES:
        if group['remote_group_view'] == get_curr_group_view():
            # select the first group
            if curr_group_in_view is not None and next_group_in_view is None:
                next_group_in_view = group
            if first_group_in_view is None:
                first_group_in_view = group
            if (CURR_GROUP['entity_id'] == group['entity_id']):
                curr_group_in_view = group

    if next_group_in_view is not None:
        selected_group = next_group_in_view
    else:
        selected_group = first_group_in_view
    CURR_GROUP = selected_group
    # to reset
    set_curr_group(hass, CURR_GROUP)


def set_prev_group(hass):
    # set focus on prev group in focused view
    global CURR_GROUP
    last_group_in_view = None
    curr_group_in_view = None
    prev_group_in_view = None
    selected_group = None
    for group in GROUP_ENTITIES:
        if group['remote_group_view'] == get_curr_group_view():
            # select the last group
            last_group_in_view = group
            if (CURR_GROUP['entity_id'] == group['entity_id']):
                curr_group_in_view = group
            if curr_group_in_view is None:
                prev_group_in_view = group
    if prev_group_in_view is not None:
        selected_group = prev_group_in_view
    else:
        selected_group = last_group_in_view
    CURR_GROUP = selected_group
    # to reset
    set_curr_group(hass, CURR_GROUP)


# entity in group
def get_curr_entity():
    global CURR_ENTITIE
    if CURR_ENTITIE is None:
        CURR_ENTITIE = GROUP_ENTITIES[get_curr_group_idx()]['entities'][0]
    return CURR_ENTITIE


def get_curr_entity_idx():
    idx = 0
    for item in GROUP_ENTITIES[get_curr_group_idx()]['entities']:
        if item == get_curr_entity():
            return idx
        idx += 1


def set_curr_entity(hass, entity):
    # set focus on current entity
    global CURR_ENTITIE
    global CURR_ENTITIE_POSITION
    if entity is None:
        CURR_ENTITIE = get_curr_entity()
    else:
        CURR_ENTITIE = entity
    CURR_ENTITIE_POSITION = None
    hass.states.async_set(
        'binary_sensor.selected_entity',
        CURR_ENTITIE)


def set_next_entity(hass):
    # set next entity
    global CURR_ENTITIE
    idx = get_curr_entity_idx()
    l_group_len = len(GROUP_ENTITIES[get_curr_group_idx()]['entities'])
    if (idx + 1 == l_group_len):
        idx = 0
    else:
        idx = idx + 1
    CURR_ENTITIE = GROUP_ENTITIES[get_curr_group_idx()]['entities'][idx]
    # to reset variables
    set_curr_entity(hass, None)
    say_curr_entity(hass)


def set_prev_entity(hass):
    # set prev entity
    global CURR_ENTITIE
    idx = get_curr_entity_idx()
    l_group_len = len(GROUP_ENTITIES[get_curr_group_idx()]['entities'])
    if (idx == 0):
        idx = l_group_len - 1
    else:
        idx = idx - 1
    CURR_ENTITIE = GROUP_ENTITIES[get_curr_group_idx()]['entities'][idx]
    # to reset variables
    set_curr_entity(hass, None)
    say_curr_entity(hass)


def say_curr_entity(hass):
    # check if we have selected item
    entity_id = get_curr_entity()
    state = hass.states.get(entity_id)
    text = state.attributes.get('text')
    if not text:
        text = ""
    # handle special cases...
    if (entity_id == "sensor.ais_knowledge_answer"):
        _say_it(hass, "Odpowiedź: " + text)
        return
    # normal case
    info_name = state.attributes.get('friendly_name')
    info_data = state.state
    info_unit = state.attributes.get('unit_of_measurement')
    # decode None
    if not info_data:
        info_data = ""
    if (info_data == 'on'):
        info_data = "włączone"
    if (info_data == 'off'):
        info_data = "wyłączone"
    if not info_unit:
        info_unit = ""
    info = "%s %s %s" % (info_name, info_data, info_unit)
    _say_it(hass, info)


def get_curent_position(hass):
    # return the entity focused position
    global CURR_ENTITIE_POSITION
    if CURR_ENTITIE_POSITION is None:
        CURR_ENTITIE_POSITION = hass.states.get(CURR_ENTITIE).state
    return CURR_ENTITIE_POSITION


def commit_current_position(hass):
    if CURR_ENTITIE.startswith('input_select.'):
        hass.services.call(
            'input_select',
            'select_option', {
                "entity_id": CURR_ENTITIE,
                "option": get_curent_position(hass)})
    elif (CURR_ENTITIE.startswith('input_number.')):
        hass.services.call(
            'input_number',
            'set_value', {
                "entity_id": CURR_ENTITIE,
                "value": get_curent_position(hass)})
    _say_it(hass, "ok")


def set_next_position(hass):
    global CURR_ENTITIE_POSITION
    CURR_ENTITIE_POSITION = get_curent_position(hass)
    state = hass.states.get(CURR_ENTITIE)
    if CURR_ENTITIE.startswith('input_select.'):
        arr = state.attributes.get('options')
        # the - option is olways first
        if len(arr) < 2:
            _say_it(hass, "brak pozycji")
        else:
            CURR_ENTITIE_POSITION = get_next(
                arr,
                CURR_ENTITIE_POSITION)
            _say_it(hass, CURR_ENTITIE_POSITION)
    elif CURR_ENTITIE.startswith('input_number.'):
        _max = int(state.attributes.get('max'))
        _step = int(state.attributes.get('step'))
        _curr = int(float(CURR_ENTITIE_POSITION))
        CURR_ENTITIE_POSITION = str(min(_curr+_step, _max))
        _say_it(hass, str(CURR_ENTITIE_POSITION))


def set_prev_position(hass):
    global CURR_ENTITIE_POSITION
    CURR_ENTITIE_POSITION = get_curent_position(hass)
    state = hass.states.get(CURR_ENTITIE)
    if CURR_ENTITIE.startswith('input_select.'):
        arr = state.attributes.get('options')
        if len(arr) < 2:
            _say_it(hass, "brak pozycji")
        else:
            CURR_ENTITIE_POSITION = get_prev(
                arr,
                CURR_ENTITIE_POSITION)
            _say_it(hass, CURR_ENTITIE_POSITION)
    elif CURR_ENTITIE.startswith('input_number.'):
        _min = int(state.attributes.get('min'))
        _step = int(state.attributes.get('step'))
        _curr = int(float(CURR_ENTITIE_POSITION))
        CURR_ENTITIE_POSITION = str(max(_curr-_step, _min))
        _say_it(hass, str(CURR_ENTITIE_POSITION))


def select_entity(hass):
    # on remote OK, select group view, group or entity
    # OK on remote
    if CURR_GROUP_VIEW is None:
        # no group view was selected
        set_curr_group_view()
        say_curr_group_view(hass)
        return
    if CURR_GROUP is None:
        # no group is selected - we need to select the first one
        # from the group view
        set_curr_group(hass, None)
        say_curr_group(hass)
        return
    if CURR_ENTITIE is None:
        # no entity is selected - we need to select the first one
        set_curr_entity(hass, None)
        say_curr_entity(hass)
        return

    # check if we can change this item
    if CURR_ENTITIE.startswith((
        "media_player.",
        "input_select.",
        "input_boolean.",
        "switch.",
        "input_number."
    )):
        # these items can be controlled from remote
        # if we are here it meens that the enter on the same item was
        # pressed twice, we should do something - to mange the item status
        if CURR_ENTITIE.startswith('input_select.'):
            commit_current_position(hass)
        elif (CURR_ENTITIE.startswith('input_number.')):
            return commit_current_position(hass)
        elif CURR_ENTITIE.startswith('media_player.'):
            # play / pause on all players
            _say_it(hass, "ok")
            hass.services.call(
                'media_player',
                'media_play_pause')
        elif (CURR_ENTITIE.startswith('input_boolean.')):
            curr_state = hass.states.get(CURR_ENTITIE).state
            if (curr_state == 'on'):
                _say_it(hass, "ok, wyłączam")
            if (curr_state == 'off'):
                _say_it(hass,  "ok, włączam")
            hass.services.call(
                'input_boolean',
                'toggle', {
                    "entity_id": CURR_ENTITIE})
        elif (CURR_ENTITIE.startswith('switch.')):
            curr_state = hass.states.get(CURR_ENTITIE).state
            if (curr_state == 'on'):
                _say_it(hass, "ok, wyłączam")
            if (curr_state == 'off'):
                _say_it(hass,  "ok, włączam")
            hass.services.call(
                'switch',
                'toggle', {
                    "entity_id": CURR_ENTITIE})
        elif (CURR_ENTITIE.startswith('input_text.')):
            _say_it(hass, "Powiedz co mam zrobić?")

    else:
        # do some special staff for some entries
        if (CURR_ENTITIE == 'sensor.version_info'):
            # get the info about upgrade
            state = hass.states.get(CURR_ENTITIE)
            upgrade = state.attributes.get('reinstall_dom_app')
            if (upgrade is True):
                _say_it(
                    hass,
                    "Aktualizuje system do najnowszej wersji. Do usłyszenia.")
                hass.services.call('ais_shell_command', 'execute_upgrade')
            else:
                _say_it(hass, "Twoja wersja jest aktualna")
        else:
            # eneter on unchanged item
            _say_it(hass, "Tej pozycji nie można zmieniać")

    hass.block_till_done()
    # say_curr_entity(hass)


def can_entity_be_changed(hass, entity):
    # check if entity can be changed
    if CURR_ENTITIE.startswith((
        "media_player.",
        "input_select.",
        "input_boolean.",
        "switch.",
        "input_number."
    )):
        return True
    else:
        return False


def set_focus_on_down_entity(hass):
    # down on joystick
    # no group is selected go to next in the groups view menu
    if CURR_GROUP is None:
            select_entity(hass)
            return
    # group is selected
    # check if the entity in the group is selected if not go to the group
    if CURR_ENTITIE is None:
            select_entity(hass)
            return
    # entity in the group is selected
    set_next_entity(hass)


def set_focus_on_up_entity(hass):
    # on joystick up
    # no group is selected go to prev in the groups view menu
    if CURR_GROUP is None:
            set_prev_group_view()
            say_curr_group_view(hass)
            return
    # group is selected
    # check if the entity in the group is selected
    if CURR_ENTITIE is None:
            set_curr_group_view()
            say_curr_group_view(hass)
            return
    # entity in the group is selected
    # check if we can go to up entity
    if get_curr_entity_idx() == 0:
        # go to group view
        set_curr_group(hass, None)
        say_curr_group(hass)
    else:
        set_prev_entity(hass)


def set_focus_on_prev_entity(hass):
    # prev on joystick
    # no group is selected go to prev in the groups view menu
    if CURR_GROUP is None:
            set_prev_group_view()
            say_curr_group_view(hass)
            return
    # group is selected
    # check if the entity in the group is selected
    if CURR_ENTITIE is None:
            set_prev_group(hass)
            say_curr_group(hass)
            return
    # entity in the group is selected
    # check if the entity option can be selected
    if can_entity_be_changed(hass, CURR_ENTITIE):
        set_prev_position(hass)
    else:
        # no way to change the entity, go to next one
        set_prev_entity(hass)


def set_focus_on_next_entity(hass):
    # next on joystick
    # no group is selected go to next in the groups view menu
    if CURR_GROUP is None:
            set_next_group_view()
            say_curr_group_view(hass)
            return
    # group is selected
    # check if the entity in the group is selected
    if CURR_ENTITIE is None:
            set_next_group(hass)
            say_curr_group(hass)
            return
    # entity in the group is selected
    # check if the entity option can be selected
    if can_entity_be_changed(hass, CURR_ENTITIE):
        set_next_position(hass)
    else:
        # no way to change the entity, go to next one
        set_next_entity(hass)


def get_groups(hass):
    global GROUP_ENTITIES
    entities = hass.states.async_all()
    GROUP_ENTITIES = []

    def add_menu_item(entity):
        _LOGGER.debug('add_menu_item ' + str(entity))
        group = {}
        group['friendly_name'] = entity.attributes.get('friendly_name')
        group['order'] = entity.attributes.get('order')
        group['entity_id'] = entity.entity_id
        group['entities'] = entity.attributes.get('entity_id')
        group['context_key_words'] = entity.attributes.get('context_key_words')
        group['context_answer'] = entity.attributes.get('context_answer')
        group['context_suffix'] = entity.attributes.get('context_suffix')
        group['remote_group_view'] = entity.attributes.get('remote_group_view')
        GROUP_ENTITIES.append(group)

    def getKey(item):
        return item['order']

    for entity in entities:
        if entity.entity_id.startswith('group.'):
            remote = entity.attributes.get('remote_group_view')
            if (remote is not None):
                if (entity.entity_id != 'group.ais_pilot'):
                    add_menu_item(entity)
    GROUP_ENTITIES = sorted(GROUP_ENTITIES, key=getKey)


@asyncio.coroutine
async def async_setup(hass, config):
    """Register the process service."""
    warnings.filterwarnings('ignore', module='fuzzywuzzy')
    config = config.get(DOMAIN, {})
    intents = hass.data.get(DOMAIN)
    if intents is None:
        intents = hass.data[DOMAIN] = {}

    for intent_type, utterances in config.get('intents', {}).items():
        conf = intents.get(intent_type)
        if conf is None:
            conf = intents[intent_type] = []
        conf.extend(_create_matcher(utterance) for utterance in utterances)

    @asyncio.coroutine
    async def process(service):
        """Parse text into commands."""
        text = service.data[ATTR_TEXT]
        callback = None
        if 'callback' in service.data:
            callback = service.data['callback']
        await _process(hass, text, callback)

    def process_code(service):
        """Parse remote code into action."""
        text = json.loads(service.data.get(ATTR_TEXT))
        _process_code(hass, text, None)

    def say_it(service):
        """Info to the user."""
        text = service.data[ATTR_TEXT]
        _say_it(hass, text)

    @asyncio.coroutine
    def publish_command_to_frame(service):
        key = service.data['key']
        val = service.data['val']
        ip = 'localhost'
        if "ip" in service.data:
            if service.data['ip'] is not None:
                ip = service.data['ip']
        _publish_command_to_frame(hass, key, val, ip)

    def process_command_from_frame(service):
        _process_command_from_frame(hass, service)

    # register services
    hass.services.async_register(DOMAIN, 'process', process)
    hass.services.async_register(DOMAIN, 'process_code', process_code)
    hass.services.async_register(DOMAIN, 'say_it', say_it)
    hass.services.async_register(
        DOMAIN, 'publish_command_to_frame', publish_command_to_frame)
    hass.services.async_register(
        DOMAIN, 'process_command_from_frame', process_command_from_frame)

    hass.helpers.intent.async_register(GetTimeIntent())
    hass.helpers.intent.async_register(GetDateIntent())
    hass.helpers.intent.async_register(TurnOnIntent())
    hass.helpers.intent.async_register(TurnOffIntent())
    hass.helpers.intent.async_register(StatusIntent())
    hass.helpers.intent.async_register(PlayRadioIntent())
    hass.helpers.intent.async_register(AisPlayPodcastIntent())
    hass.helpers.intent.async_register(AisPlayYtMusicIntent())
    hass.helpers.intent.async_register(AskQuestionIntent())
    hass.helpers.intent.async_register(ChangeContextIntent())
    hass.helpers.intent.async_register(AisGetWeather())
    hass.helpers.intent.async_register(AisGetWeather48())
    hass.helpers.intent.async_register(AisLampsOn())
    hass.helpers.intent.async_register(AisLampsOff())
    hass.helpers.intent.async_register(AisSwitchesOn())
    hass.helpers.intent.async_register(AisSwitchesOff())
    async_register(hass, INTENT_GET_WEATHER, [
            'pogoda',
            'pogoda w {location}',
            'pogoda we {location}',
            'jaka jest pogoda',
            'jaka jest pogoda w {location}',
            'jaka jest pogoda we {location}',
            'czy jest słonecznie w {location}',
            'czy jest słonecznie we {location}'
    ])
    async_register(hass, INTENT_GET_WEATHER_48, [
            'prognoza pogody',
            'pogoda prognoza',
            'pogoda jutro',
            'pogoda jutro w {location}',
            'pogoda jutro we {location}',
            'jaka będzie pogoda',
            'jaka będzie pogoda w {location}',
            'jaka będzie pogoda we {location}',
            'czy będzie słonecznie w {location}'
    ])
    async_register(hass, INTENT_LAMPS_ON, [
            'włącz światła',
            'zapal światła',
            'włącz wszystkie światła',
            'zapal wszystkie światła'
    ])
    async_register(hass, INTENT_LAMPS_OFF, [
            'zgaś światła',
            'wyłącz światła',
            'wyłącz wszystkie światła',
            'zgaś wszystkie światła'
    ])
    async_register(hass, INTENT_SWITCHES_ON, [
            'włącz przełączniki',
            'włącz wszystkie przełączniki'
    ])
    async_register(hass, INTENT_SWITCHES_OFF, [
            'wyłącz przełączniki',
            'wyłącz wszystkie przełączniki'
    ])
    async_register(hass, INTENT_GET_TIME, [
            'która [jest] [teraz] godzina',
            'którą mamy godzinę',
            'jaki [jest] czas',
            '[jaka] [jest] godzina',
    ])
    async_register(hass, INTENT_GET_DATE, [
            '[jaka] [jest] data',
            'jaki [mamy] [jest] [dzisiaj] dzień',
            'co dzisiaj jest',
            'co [mamy] [jest] dzisiaj',
    ])
    async_register(hass, INTENT_PLAY_RADIO, [
        'Radio {item}',
        'Włącz radio {item}',
        'Graj radio {item}',
        'Graj {item} radio',
        'Przełącz [na] radio [na] {item}',
        'Posłuchał bym radio {item}',
        'Włącz stację radiową {item}',
    ])
    async_register(hass, INTENT_PLAY_PODCAST, [
        'Podcast {item}',
        'Włącz podcast {item}',
        'Graj podcast {item}',
        'Graj {item} podcast',
        'Przełącz [na] podcast {item}',
        'Posłuchał bym podcast {item}',
    ])
    async_register(hass, INTENT_PLAY_YT_MUSIC, [
        'Muzyka {item}',
        'Włącz muzykę {item}',
        'Graj muzykę {item}',
        'Graj {item} muzykę',
        'Przełącz [na] muzykę [na] {item}',
        'Posłuchał bym muzykę {item}',
        'Włącz [z] [na] YouTube {item}',
        'YouTube {item}'
    ])
    async_register(hass, INTENT_TURN_ON,
                   ['Włącz {name}', 'Zapal światło w {name}'])
    async_register(hass, INTENT_TURN_OFF,
                   ['Wyłącz {name}', 'Zgaś Światło w {name}'])
    async_register(hass, INTENT_STATUS, [
        'Jaka jest {name}', 'Jaki jest {name}',
        'Jak jest {name}', 'Jakie jest {name}'])
    async_register(hass, INTENT_ASK_QUESTION, [
        'Co to jest {item}', 'Kto to jest {item}',
        'Znajdź informację o {item}', 'Znajdź informacje o {item}',
        'Wyszukaj informację o {item}', 'Wyszukaj informacje o {item}',
        'Wyszukaj {item}', 'Kim jest {item}', 'Informacje o {item}',
        'Czym jest {item}', 'Opowiedz mi o {intem}',
        'Informację na temat {item}', 'Co wiesz o {item}',
        'Co wiesz na temat {item}', 'Opowiedz o {item}',
        'Kim są {item}', 'Kto to {item}'])
    # get groups to create the context dynamically
    if (len(GROUP_ENTITIES) == 0):
        get_groups(hass)
    # register context intent
    for menu in GROUP_ENTITIES:
        context_key_words = menu['context_key_words']
        if context_key_words is not None:
            context_key_words = context_key_words.split(',')
            async_register(hass, INTENT_CHANGE_CONTEXT, context_key_words)
    return True


def _publish_command_to_frame(hass, key, val, ip):
    # sent the command to the android frame via http
    url = G_HTTP_REST_SERVICE_BASE_URL.format(ip)
    requests.post(
        url + '/command',
        json={key: val, "ip": ip})


def _process_command_from_frame(hass, service):
    # process from frame
    if service.data["topic"] == 'ais/speech_command':
        hass.async_add_job(
            _process(
                hass, service.data["payload"], service.data["callback"])
        )
    elif service.data["topic"] == 'ais/key_command':
        hass.async_run_job(
            _process_code(
                hass, json.loads(service.data["payload"]),
                service.data["callback"])
        )
    else:
        # TODO process this without mqtt
        # player_status and speech_status
        mqtt.async_publish(
            hass, service.data["topic"], service.data["payload"], 2)
        # TODO


def _post_message(message, host):
    """Post the message to TTS service."""
    try:
        url = G_HTTP_REST_SERVICE_BASE_URL.format(host)
        requests.post(
            url + '/text_to_speech',
            json={
                "text": message,
                "pitch": ais_global.GLOBAL_TTS_PITCH,
                "rate": ais_global.GLOBAL_TTS_RATE,
                "voice": ais_global.GLOBAL_TTS_VOICE
                })
    except Exception as e:
        if host != 'localhost':
            _LOGGER.error(
                "problem to send the text to speech via http: " + str(e))


def _say_it(hass, message, caller_ip=None):
    # sent the tts message to the panel via http api
    global GLOBAL_TTS_TEXT
    _post_message(message, 'localhost')
    # check if we should inform other speaker
    player_name = hass.states.get('input_select.tts_player').state
    device_ip = None
    if player_name is not None:
        device = ais_cloud.get_player_data(player_name)
        if device is not None:
            device_ip = device["device_ip"]
            if device_ip not in ['localhost', '127.0.0.1']:
                _post_message(message, device_ip)

    # check if we should inform back the caller speaker
    # the local caller has ip like 192.168.1.45
    internal_ip = hass.states.get('sensor.internal_ip_address').state
    if caller_ip is not None:
        if caller_ip not in ['localhost', '127.0.0.1', device_ip, internal_ip]:
            _post_message(message, caller_ip)

    if len(message) > 199:
        GLOBAL_TTS_TEXT = message[0: 199] + '...'
    else:
        GLOBAL_TTS_TEXT = message
    hass.states.async_set(
        'sensor.ais_knowledge_answer', 'ok', {
            'custom_ui_state_card': 'state-card-text',
            'text': GLOBAL_TTS_TEXT
            })


def _create_matcher(utterance):
    """Create a regex that matches the utterance."""
    # Split utterance into parts that are type: NORMAL, GROUP or OPTIONAL
    # Pattern matches (GROUP|OPTIONAL): Change light to [the color] {name}
    parts = re.split(r'({\w+}|\[[\w\s]+\] *)', utterance)
    # Pattern to extract name from GROUP part. Matches {name}
    group_matcher = re.compile(r'{(\w+)}')
    # Pattern to extract text from OPTIONAL part. Matches [the color]
    optional_matcher = re.compile(r'\[([\w ]+)\] *')

    pattern = ['^']
    for part in parts:
        group_match = group_matcher.match(part)
        optional_match = optional_matcher.match(part)

        # Normal part
        if group_match is None and optional_match is None:
            pattern.append(part)
            continue

        # Group part
        if group_match is not None:
            pattern.append(
                r'(?P<{}>[\w ]+?)\s*'.format(group_match.groups()[0]))

        # Optional part
        elif optional_match is not None:
            pattern.append(r'(?:{} *)?'.format(optional_match.groups()[0]))

    pattern.append('$')
    return re.compile(''.join(pattern), re.I)


def _process_code(hass, data, callback):
    """Process a code from remote."""
    global CURR_BUTTON_CODE
    if 'Action' in data:
        action = data["Action"]
        if action == 1:
            return
    # check if we have callback
    if callback is not None:
        # TODO the answer should go to the correct clien
        pass
    code = data["KeyCode"]
    _LOGGER.info("KeyCode: -> " + str(code))
    # set the conde in global variabl
    CURR_BUTTON_CODE = code
    # show the code in web app
    hass.states.set('binary_sensor.ais_remote_button', code)
    # decode Key Events
    # codes acording to android.view.KeyEvent
    if code == 93:
        # PG- -> KEYCODE_PAGE_DOWN
        pass
    if code == 92:
        # PG+ -> KEYCODE_PAGE_UP
        pass
    if code == 4:
        # Back arrow -> KEYCODE_BACK
        pass
    if code == 82:
        # Menu -> KEYCODE_MENU
        set_next_group_view()
        say_curr_group_view(hass)
    if code == 164:
        # Mute -> KEYCODE_VOLUME_MUTE
        pass
    if code == 71:
        # MIC DOWN -> KEYCODE_LEFT_BRACKET
        hass.states.set('binary_sensor.ais_remote_mic', 'on')
    if code == 72:
        # MIC UP -> KEYCODE_RIGHT_BRACKET
        hass.states.set('binary_sensor.ais_remote_mic', 'off')
    if code == 20:
        # Dpad down -> KEYCODE_DPAD_DOWN
        set_focus_on_down_entity(hass)
    if code == 21:
        # Dpad left -> KEYCODE_DPAD_LEFT
        set_focus_on_prev_entity(hass)
    if code == 22:
        # Dpad right -> KEYCODE_DPAD_RIGHT
        set_focus_on_next_entity(hass)
    if code == 19:
        set_focus_on_up_entity(hass)
    if code == 23:
        # Dpad center -> KEYCODE_DPAD_CENTER
        select_entity(hass)
    if code == 25:
        # Volume down -> KEYCODE_VOLUME_DOWN
        pass
    if code == 24:
        # Volume up -> KEYCODE_VOLUME_UP
        pass
    if code == 190:
        # stop the audio -> KEYCODE_HOME
        hass.services.call('media_player', 'media_play_pause')


@asyncio.coroutine
def _process(hass, text, callback):
    """Process a line of text."""
    _LOGGER.info('Process text: ' + text)
    global CURR_BUTTON_CODE
    intent_resp = None
    s = False
    m = None
    found = False
    intents = hass.data.get(DOMAIN, {})
    try:
        for intent_type, matchers in intents.items():
            if found:
                break
            for matcher in matchers:
                match = matcher.match(text)
                if match:
                    # we havee a match
                    found = True
                    m, s = yield from hass.helpers.intent.async_handle(
                        DOMAIN, intent_type,
                        {key: {'value': value} for key, value
                         in match.groupdict().items()}, text)
                    break
        # the was no match - try again but with context
        if not found:
            sufix = GROUP_ENTITIES[get_curr_group_idx()]['context_suffix']
            if sufix is not None:
                for intent_type, matchers in intents.items():
                    if found:
                        break
                    for matcher in matchers:
                        match = matcher.match(sufix + " " + text)
                        if match:
                            # we havee a match
                            found = True
                            m, s = yield from hass.helpers.intent.async_handle(
                                DOMAIN, intent_type,
                                {key: {'value': value} for key, value
                                 in match.groupdict().items()},
                                sufix + " " + text)
                            # reset the curr button code
                            # TODO the mic shoud send a button code too
                            # in this case we will know if the call source
                            CURR_BUTTON_CODE = 0
                            break
        if s is False or not found:
            # no success - try to ask the cloud
            if m is None:
                # no message / no match
                m = 'Nie rozumiem ' + text
            # asking without the sufix
            ws_resp = aisCloudWS.ask(text, m)
            m = ws_resp.text

    except Exception as e:
        _LOGGER.error('_process: ' + str(e))
        m = "Przepraszam, ale mam problem ze zrozumieniem: " + text
    # return response to the ais dom
    if m != 'DO_NOT_SAY':
        _say_it(hass, m, callback)
    # return response to the hass conversation
    intent_resp = intent.IntentResponse()
    intent_resp.async_set_speech(m)
    intent_resp.hass = hass
    return intent_resp


@core.callback
def _match_entity(hass, name):
    """Match a name to an entity."""
    from fuzzywuzzy import process as fuzzyExtract
    entities = {state.entity_id: state.name for state
                in hass.states.async_all()}
    try:
        entity_id = fuzzyExtract.extractOne(
            name, entities, score_cutoff=88)[2]
    except Exception as e:
        entity_id = None

    if entity_id is not None:
        return hass.states.get(entity_id)
    else:
        return None


class TurnOnIntent(intent.IntentHandler):
    """Handle turning item on intents."""

    intent_type = INTENT_TURN_ON
    slot_schema = {
        'name': cv.string,
    }

    @asyncio.coroutine
    def async_handle(self, intent_obj):
        """Handle turn on intent."""
        hass = intent_obj.hass
        slots = self.async_validate_slots(intent_obj.slots)
        name = slots['name']['value']
        entity = _match_entity(hass, name)
        success = False

        if not entity:
            message = 'Nie znajduję urządzenia do włączenia, o nazwie: ' + name
        else:
            # check if we can turn_on on this device
            if isSwitch(entity.entity_id):
                if entity.state == 'on':
                    # check if the device is already on
                    message = 'Urządzenie ' + name + ' jest już włączone'
                elif entity.state == 'unavailable':
                    message = 'Urządzenie ' + name + ' jest niedostępne'
                else:
                    yield from hass.services.async_call(
                        core.DOMAIN, SERVICE_TURN_ON, {
                            ATTR_ENTITY_ID: entity.entity_id,
                        }, blocking=True)
                    message = 'OK, włączono {}'.format(entity.name)
                    success = True
            else:
                message = 'Urządzenia ' + name + ' nie można włączyć'
        return message, success


class TurnOffIntent(intent.IntentHandler):
    """Handle turning item off intents."""

    intent_type = INTENT_TURN_OFF
    slot_schema = {
        'name': cv.string,
    }

    @asyncio.coroutine
    def async_handle(self, intent_obj):
        """Handle turn off intent."""
        hass = intent_obj.hass
        slots = self.async_validate_slots(intent_obj.slots)
        name = slots['name']['value']
        entity = _match_entity(hass, name)
        success = False
        if not entity:
            msg = 'Nie znajduję urządzenia do wyłączenia, o nazwie: ' + name
        else:
            # check if we can turn_off on this device
            if isSwitch(entity.entity_id):
                # check if the device is already pff
                if entity.state == 'off':
                    msg = 'Urządzenie {} jest już wyłączone'.format(
                        entity.name)
                elif entity.state == 'unavailable':
                    msg = 'Urządzenie {}} jest niedostępne'.format(
                        entity.name)
                else:
                    yield from hass.services.async_call(
                        core.DOMAIN, SERVICE_TURN_OFF, {
                            ATTR_ENTITY_ID: entity.entity_id,
                        }, blocking=True)
                    msg = 'OK, wyłączono {}'.format(entity.name)
                    success = True
            else:
                msg = 'Urządzenia ' + name + ' nie można wyłączyć'
        return msg, success


class StatusIntent(intent.IntentHandler):
    """Handle status item on intents."""

    intent_type = INTENT_STATUS
    slot_schema = {
        'name': cv.string,
    }

    @asyncio.coroutine
    def async_handle(self, intent_obj):
        """Handle status intent."""
        hass = intent_obj.hass
        slots = self.async_validate_slots(intent_obj.slots)
        name = slots['name']['value']
        entity = _match_entity(hass, name)
        success = False

        if not entity:
            message = 'Nie znajduję informacji o: ' + name
            success = False
        else:
            unit = entity.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
            if unit is None:
                value = entity.state
            else:
                value = "{} {}".format(entity.state, unit)
            message = format(entity.name) + ': ' + value
            success = True
        return message, success


class PlayRadioIntent(intent.IntentHandler):
    """Handle PlayRadio intents."""

    intent_type = INTENT_PLAY_RADIO
    slot_schema = {
        'item': cv.string
    }

    @asyncio.coroutine
    def async_handle(self, intent_obj):
        """Handle the intent."""
        hass = intent_obj.hass
        slots = self.async_validate_slots(intent_obj.slots)
        item = slots['item']['value']
        station = item
        success = False
        if not station:
            message = 'Nie wiem jaką stację chcesz włączyć.'
        else:
            ws_resp = aisCloudWS.audio(
                station, ais_global.G_AN_RADIO, intent_obj.text_input)
            json_ws_resp = ws_resp.json()
            json_ws_resp["audio_type"] = ais_global.G_AN_RADIO
            name = json_ws_resp['name']
            if len(name.replace(" ", "")) == 0:
                message = "Niestety nie znajduję radia " + station
            else:
                yield from hass.services.async_call(
                     'ais_cloud', 'play_audio',
                     json_ws_resp, blocking=False)
                message = "OK, włączam radio " + name
                success = True
        return message, success


class AisPlayPodcastIntent(intent.IntentHandler):
    """Handle Podcast intents."""

    intent_type = INTENT_PLAY_PODCAST
    slot_schema = {
        'item': cv.string
    }

    @asyncio.coroutine
    def async_handle(self, intent_obj):
        """Handle the intent."""
        hass = intent_obj.hass
        slots = self.async_validate_slots(intent_obj.slots)
        item = slots['item']['value']
        success = False

        if not item:
            message = 'Nie wiem jaką audycję chcesz posłuchać.'
        else:
            ws_resp = aisCloudWS.audio(
                item, ais_global.G_AN_PODCAST, intent_obj.text_input)
            json_ws_resp = ws_resp.json()
            json_ws_resp["audio_type"] = ais_global.G_AN_PODCAST
            name = json_ws_resp['name']
            if len(name.replace(" ", "")) == 0:
                message = "Niestety nie znajduję podcasta " + item
            else:
                yield from hass.services.async_call(
                     'ais_cloud', 'play_audio',
                     json_ws_resp, blocking=False)
                message = "OK, pobieram odcinki audycji " + item
                success = True
        return message, success


class AisPlayYtMusicIntent(intent.IntentHandler):
    """Handle Music intents."""

    intent_type = INTENT_PLAY_YT_MUSIC
    slot_schema = {
        'item': cv.string
    }

    @asyncio.coroutine
    def async_handle(self, intent_obj):
        """Handle the intent."""
        hass = intent_obj.hass
        slots = self.async_validate_slots(intent_obj.slots)
        item = slots['item']['value']
        success = False

        if not item:
            message = 'Nie wiem jaką muzykę mam szukać '
        else:
            success = True
            yt_query = {}
            yt_query["audio_type"] = ais_global.G_AN_MUSIC
            yt_query["text"] = item
            yield from hass.services.async_call(
                 'ais_cloud', 'play_audio',
                 yt_query, blocking=False)
            message = "OK, szukam na YouTube " + item
            success = True
        return message, success


class AskQuestionIntent(intent.IntentHandler):
    """Handle AskQuestion intents."""

    intent_type = INTENT_ASK_QUESTION
    slot_schema = {
        'item': cv.string
    }

    @asyncio.coroutine
    def async_handle(self, intent_obj):
        """Handle the intent."""
        hass = intent_obj.hass
        slots = self.async_validate_slots(intent_obj.slots)
        item = slots['item']['value']
        question = item
        if not question:
            message = 'Nie wiem o co zapytać, ' + question
            return message, False
        else:
            yield from hass.services.async_call(
                 'ais_knowledge_service',
                 'ask', {"text": question, "say_it": True}, blocking=True)
        return 'DO_NOT_SAY', True


class ChangeContextIntent(intent.IntentHandler):
    """Handle ChangeContext intents."""
    intent_type = INTENT_CHANGE_CONTEXT

    @asyncio.coroutine
    def async_handle(self, intent_obj):
        """Handle the intent."""
        hass = intent_obj.hass
        if (len(GROUP_ENTITIES) == 0):
            get_groups(hass)
        text = intent_obj.text_input.lower()
        _LOGGER.debug('text: ' + text)
        for idx, menu in enumerate(GROUP_ENTITIES, start=0):
            context_key_words = menu['context_key_words']
            if context_key_words is not None:
                context_key_words = context_key_words.split(',')
                if text in context_key_words:
                    set_curr_group(hass, menu)
                    set_curr_entity(hass, None)
                    message = menu['context_answer']
                    return message, True

        message = 'Nie znajduję odpowiedzi do kontekstu ' + text
        return message, False


class GetTimeIntent(intent.IntentHandler):
    """Handle GetTimeIntent intents."""
    intent_type = INTENT_GET_TIME

    @asyncio.coroutine
    def async_handle(self, intent_obj):
        """Handle the intent."""
        hass = intent_obj.hass
        time = hass.states.get('sensor.time').state
        message = 'Jest godzina ' + time
        return message, True


class AisGetWeather(intent.IntentHandler):
    """Handle GetWeather intents."""
    intent_type = INTENT_GET_WEATHER

    @asyncio.coroutine
    def async_handle(self, intent_obj):
        """Handle the intent."""
        hass = intent_obj.hass
        weather = hass.states.get('sensor.pogoda_info').state
        return weather, True


class AisGetWeather48(intent.IntentHandler):
    """Handle GetWeather48 intents."""
    intent_type = INTENT_GET_WEATHER_48

    @asyncio.coroutine
    def async_handle(self, intent_obj):
        """Handle the intent."""
        hass = intent_obj.hass
        weather = hass.states.get('sensor.prognoza_info').state
        return weather, True


class AisLampsOn(intent.IntentHandler):
    """Handle AisLampsOn intents."""
    intent_type = INTENT_LAMPS_ON

    @asyncio.coroutine
    def async_handle(self, intent_obj):
        """Handle the intent."""
        hass = intent_obj.hass
        yield from hass.services.async_call(
             'light', 'turn_on', {"entity_id": "group.all_lights"})
        return 'ok', True


class AisLampsOff(intent.IntentHandler):
    """Handle AisLampsOff intents."""
    intent_type = INTENT_LAMPS_OFF

    @asyncio.coroutine
    def async_handle(self, intent_obj):
        """Handle the intent."""
        hass = intent_obj.hass
        yield from hass.services.async_call(
             'light', 'turn_off', {"entity_id": "group.all_lights"})
        return 'ok', True


class AisSwitchesOn(intent.IntentHandler):
    """Handle AisSwitchesOn intents."""
    intent_type = INTENT_SWITCHES_ON

    @asyncio.coroutine
    def async_handle(self, intent_obj):
        """Handle the intent."""
        hass = intent_obj.hass
        yield from hass.services.async_call(
             'switch', 'turn_on', {"entity_id": "group.all_switches"})
        return 'ok', True


class AisSwitchesOff(intent.IntentHandler):
    """Handle AisSwitchesOff intents."""
    intent_type = INTENT_SWITCHES_OFF

    @asyncio.coroutine
    def async_handle(self, intent_obj):
        """Handle the intent."""
        hass = intent_obj.hass
        yield from hass.services.async_call(
             'switch', 'turn_off', {"entity_id": "group.all_switches"})
        return 'ok', True


class GetDateIntent(intent.IntentHandler):
    """Handle GetDateIntent intents."""
    intent_type = INTENT_GET_DATE

    @asyncio.coroutine
    def async_handle(self, intent_obj):
        """Handle the intent."""
        import babel.dates
        now = datetime.datetime.now()
        message = 'Jest ' + babel.dates.format_date(
            now, format='full', locale='pl')
        return message, True