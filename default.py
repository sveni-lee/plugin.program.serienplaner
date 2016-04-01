#!/usr/bin/python

###########################################################################
#
#          FILE:  plugin.program.serienplaner/default.py
#
#        AUTHOR:  sveni_lee
#
#       LICENSE:  GPLv3 <http://www.gnu.org/licenses/gpl.txt>
#       VERSION:  0.0.1
#       CREATED:  17.3.2016
#
###########################################################################

import urllib
import urllib2
import os
import re
import sys
import xbmc
import xbmcgui
import xbmcaddon
import time
import datetime
import json
from datetime import timedelta
import _strptime
from xml.dom import minidom

from resources.lib.serienplaner import WLScraper

__addon__ = xbmcaddon.Addon()
__addonID__ = __addon__.getAddonInfo('id')
__addonname__ = __addon__.getAddonInfo('name')
__version__ = __addon__.getAddonInfo('version')
__path__ = __addon__.getAddonInfo('path')
__LS__ = __addon__.getLocalizedString
__icon__ = xbmc.translatePath(os.path.join(__path__, 'icon.png'))

__showOutdated__ = True if __addon__.getSetting('showOutdated').upper() == 'TRUE' else False
__maxHLCat__ = int(re.match('\d+', __addon__.getSetting('max_hl_cat')).group())
__prefer_hd__ = True if __addon__.getSetting('prefer_hd').upper() == 'TRUE' else False
__firstaired__ = True if __addon__.getSetting('first_aired').upper() == 'TRUE' else False
__series_in_db__ = True if __addon__.getSetting('episode_not_in_db').upper() == 'TRUE' else False

WINDOW = xbmcgui.Window(10000)
OSD = xbmcgui.Dialog()
WLURL = 'http://www.wunschliste.de/serienplaner/'

# Helpers

def notifyOSD(header, message, icon=xbmcgui.NOTIFICATION_INFO, disp=4000, enabled=True):
    if enabled:
        OSD.notification(header.encode('utf-8'), message.encode('utf-8'), icon, disp)

def writeLog(message, level=xbmc.LOGNOTICE):
        try:
            xbmc.log('[%s %s]: %s' % (__addonID__, __version__,  message.encode('utf-8')), level)
        except Exception:
            xbmc.log('[%s %s]: %s' % (__addonID__, __version__,  'Fatal: Message could not displayed'), xbmc.LOGERROR)

# End Helpers

ChannelTranslateFile = xbmc.translatePath(os.path.join(__path__, 'ChannelTranslate.json')) 
with open(ChannelTranslateFile, 'r') as transfile:
    ChannelTranslate=transfile.read().rstrip('\n')

TVShowTranslateFile = xbmc.translatePath(os.path.join(__path__, 'TVShowTranslate.json'))
with open(TVShowTranslateFile, 'r') as transfile:
    TVShowTranslate=transfile.read().rstrip('\n')

SPWatchtypes = {'international': 1, 'german': 5, 'classics': 3, 'soap': 2}
SPTranslations = {'international': __LS__(30120), 'german': __LS__(30121), 'classics': __LS__(30122), 'soap': __LS__(30123)}
SPTranslations1 = {__LS__(30120): 'international', __LS__(30121): 'german', __LS__(30122): 'classics', __LS__(30123): 'soap'}
properties = ['ID', 'Staffel', 'Episode', 'Title', 'Starttime', 'Datum', 'neueEpisode', 'Channal', 'Logo', 'PVRID', 'Description', 'Ratin', 'Altersfreigabe', 'Genre', 'Studio', 'Jahr', 'Thumb', 'FirstAired', 'RunningTime', 'Poster', 'WatchType']

# create category list from selection in settings

def categories():
    cats = []
    for category in SPWatchtypes:
        if __addon__.getSetting(category).upper() == 'TRUE': cats.append(category)
    return cats

# get remote URL, replace '\' and optional split into css containers

def getUnicodePage(url, container=None):
    try:
        headers = { 'User-Agent' : 'Mozilla/5.0' }
        req = urllib2.Request(url, None, headers)
    except UnicodeDecodeError:
        req = urllib2.urlopen(url)

    encoding = 'utf-8'
    if "content-type" in req.headers and "charset=" in req.headers['content-type']:
        encoding=req.headers['content-type'].split('charset=')[-1]
    content = unicode(urllib2.urlopen(req).read(), encoding).replace("\\", "")
    if container is None: return content
    return content.split(container)

def getUnicodePage2(url):
    req = urllib2.Request(url)
    content = unicode(urllib2.urlopen(req).read(), "utf-8")
    content = content.replace("\\","")
    return content


# get parameter hash, convert into parameter/value pairs, return dictionary

def parameters_string_to_dict(parameters):
    paramDict = {}
    if parameters:
        paramPairs = parameters[1:].split("&")
        for paramsPair in paramPairs:
            paramSplits = paramsPair.split('=')
            if (len(paramSplits)) == 2:
                paramDict[paramSplits[0]] = paramSplits[1]
    return paramDict

# get used dateformat of kodi

def getDateFormat():
    df = xbmc.getRegion('dateshort')
    tf = xbmc.getRegion('time').split(':')

    try:
        # time format is 12h with am/pm
        return df + ' ' + tf[0][0:2] + ':' + tf[1] + ' ' + tf[2].split()[1]
    except IndexError:
        # time format is 24h with or w/o leading zero
        return df + ' ' + tf[0][0:2] + ':' + tf[1]

# convert datetime string to timestamp with workaround python bug (http://bugs.python.org/issue7980) - Thanks to BJ1

def date2timeStamp(date, format):
    try:
        dtime = datetime.datetime.strptime(date, format)
    except TypeError:
        try:
            dtime = datetime.datetime.fromtimestamp(time.mktime(time.strptime(date, format)))
        except ValueError:
            return False
    except Exception:
        return False
    return int(time.mktime(dtime.timetuple()))

##########################################################################################################################
## get pvr channel-id
##########################################################################################################################
def channelName2channelId(channelname):
    query = {
            "jsonrpc": "2.0",
            "method": "PVR.GetChannels",
            "params": {"channelgroupid": "alltv"},
            "id": 1
            }
    res = json.loads(xbmc.executeJSONRPC(json.dumps(query, encoding='utf-8')))

    # translate via json if necessary
    trans = json.loads(str(ChannelTranslate))
    for tr in trans:
        if channelname == tr['name']:
            writeLog("Translating %s to %s" % (channelname,tr['pvrname']), level=xbmc.LOGDEBUG)
            channelname = tr['pvrname']
    
    if 'result' in res and 'channels' in res['result']:
        res = res['result'].get('channels')
        for channels in res:

            # prefer HD Channel if available
            if __prefer_hd__ and  (channelname + " HD").lower() in channels['label'].lower():
                writeLog("SerienPlaner found HD priorized channel %s" % (channels['label']), level=xbmc.LOGDEBUG)
                return channels['channelid']

            if channelname.lower() in channels['label'].lower():
                writeLog("TVHighlights found channel %s" % (channels['label']), level=xbmc.LOGDEBUG)
                return channels['channelid']
    return False

##########################################################################################################################
## get TVShow-ID 
##########################################################################################################################
def TVShowName2TVShowID(tvshowname):
    query = {
            "jsonrpc": "2.0",
            "method": "VideoLibrary.GetTVShows",
            "params": {
                "properties": ["originaltitle", "imdbnumber"]
            },
            "id": "libTvShows"
            }
    
    res = json.loads(xbmc.executeJSONRPC(json.dumps(query, encoding='utf-8')))

    try:
        if 'result' in res and 'tvshows' in res['result']:
            res = res['result']['tvshows']
            for tvshow in res:
                if tvshow['label'] == tvshowname:
                    return tvshow['imdbnumber']
        return False
    except Exception:
        writeLog("JSON query returns an error", level=xbmc.LOGDEBUG)
        return False

##########################################################################################################################
## get TVShow-ID 
##########################################################################################################################

def get_thetvdbID(tvshowname):

            # translate via json if necessary
    trans = json.loads(str(TVShowTranslate))
    for tr in trans:
        if tvshowname == tr['name']:
            writeLog("Translating %s to %s" % (tvshowname,tr['tvshow']), level=xbmc.LOGDEBUG)
            tvshowname = tr['tvshow']

    tvshowname = tvshowname.replace('&', '')
    tvshowname = tvshowname.replace('and', '')    

    tvshowname = tvshowname.encode("utf-8")
    url_str="http://thetvdb.com/api/GetSeries.php?seriesname="+tvshowname
    xml_str = urllib.urlopen(url_str).read()
    xmldoc = minidom.parseString(xml_str)

    series_detail = xmldoc.getElementsByTagName("Series")

    try:        
        for Series in series_detail:
            imdbid = Series.getElementsByTagName("id")[0].firstChild.nodeValue
            writeLog("Serie hat ID %s auf the TVDB" % (imdbid), level=xbmc.LOGDEBUG) 
            return imdbid
    except Exception:
        writeLog("Serie nicht auf the TVDB", level=xbmc.LOGDEBUG)
        return False

##########################################################################################################################
## get TVShow-Poster DB
##########################################################################################################################
def TVShowName2TVShow_Detais(tvshowname):
    query = {
            "jsonrpc": "2.0",
            "method": "VideoLibrary.GetTVShows",
            "params": {
                "properties": ["originaltitle", "thumbnail", "genre", "studio", "mpaa", "year"]
            },
            "id": "libTvShows"
            }
    
    res = json.loads(xbmc.executeJSONRPC(json.dumps(query, encoding='utf-8')))
    try:
        if 'result' in res and 'tvshows' in res['result']:
            res = res['result']['tvshows']
            for tvshow in res:
                if tvshow['label'] == tvshowname:
                    return {'_genre' : tvshow['genre'], '_posterUrl' : tvshow['thumbnail'], '_studio' : tvshow['studio'], '_mpaa' : tvshow['mpaa'], '_year' : tvshow['year']}
    except Exception:
        writeLog("JSON query returns an error", level=xbmc.LOGDEBUG)
        return False      

##########################################################################################################################
## get TVShow-Poster THE TVDB
##########################################################################################################################

def get_thetvdbPoster(imdbnumber):
    url_str="http://thetvdb.com/api/DECE3B6B5464C552/series/%s/de.xml" % (imdbnumber)
    xml_str = urllib.urlopen(url_str).read()
    xmldoc = minidom.parseString(xml_str)

    poster_detail = xmldoc.getElementsByTagName("Series")

    try:        
        for Series in poster_detail:
            poster = Series.getElementsByTagName("poster")[0].firstChild.nodeValue
            genre = Series.getElementsByTagName("Genre")[0].firstChild.nodeValue
            genre = genre[1:-1]
            genre = genre.replace('|',' | ').strip()
            studio = Series.getElementsByTagName("Network")[0].firstChild.nodeValue
            content_rating = Series.getElementsByTagName("ContentRating")[0].firstChild.nodeValue
            status = Series.getElementsByTagName("Status")[0].firstChild.nodeValue
            year = Series.getElementsByTagName("FirstAired")[0].firstChild.nodeValue
            year = year[:-6]
            return {'_genre' : genre, '_posterUrl' : poster, '_studio' : studio, 'content_rating' : content_rating, 'status' : status, 'year' : year}
    except Exception:
        writeLog("Poster nicht auf the TVDB", level=xbmc.LOGDEBUG)
        return 0


##########################################################################################################################
## get pvr channelname by id
##########################################################################################################################

def pvrchannelid2channelname(channelid):
    query = {
            "jsonrpc": "2.0",
            "method": "PVR.GetChannels",
            "params": {"channelgroupid": "alltv"},
            "id": 1
            }
    res = json.loads(xbmc.executeJSONRPC(json.dumps(query, encoding='utf-8')))
    if 'result' in res and 'channels' in res['result']:
        res = res['result'].get('channels')
        for channels in res:
            if channels['channelid'] == channelid:
                writeLog("SerienPlaner found id for channel %s" % (channels['label']), level=xbmc.LOGDEBUG)
                return channels['label']
    return False

##########################################################################################################################
## get pvr channel logo url
##########################################################################################################################

def pvrchannelid2logo(channelid):
    query = {
            "jsonrpc": "2.0",
            "method": "PVR.GetChannelDetails",
            "params": {"channelid": channelid, "properties": ["thumbnail"]},
            "id": 1
            }
    res = json.loads(xbmc.executeJSONRPC(json.dumps(query, encoding='utf-8')))
    if 'result' in res and 'channeldetails' in res['result'] and 'thumbnail' in res['result']['channeldetails']:
        return res['result']['channeldetails']['thumbnail']
    else:
        return False


##########################################################################################################################
## switch tu channel
##########################################################################################################################

def switchToChannel(pvrid):
    writeLog('Switch to channel id %s' % (pvrid), level=xbmc.LOGDEBUG)
    query = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "Player.Open",
        "params": {"item": {"channelid": pvrid}}
        }
    res = json.loads(xbmc.executeJSONRPC(json.dumps(query, encoding='utf-8')))
    if 'result' in res and res['result'] == 'OK':
        return True
    else:
        writeLog('Couldn\'t switch to channel id %s' % (pvrid), level=xbmc.LOGDEBUG)
    return False

##########################################################################################################################
## clear all info properties (info window) in Home Window
##########################################################################################################################

def clearInfoProperties():
    writeLog('clear all info properties (used in info popup)', level=xbmc.LOGDEBUG)
    for property in infoprops:
        WINDOW.clearProperty('TVHighlightsToday.Info.%s' % (property))
    for i in range(1, 6, 1):
        WINDOW.clearProperty('TVHighlightsToday.RatingType.%s' % (i))
        WINDOW.clearProperty('TVHighlightsToday.Rating.%s' % (i))

##########################################################################################################################
## clear content of widgets in Home Window
##########################################################################################################################

def clearWidgets(start_from=1):
    writeLog('Clear widgets from #%s and up' % (start_from), level=xbmc.LOGDEBUG)
    for i in range(start_from, 17, 1):
        for property in properties:
            WINDOW.clearProperty('SerienPlaner.%s.%s' % (i, property))

def refreshWidget(category, offset=0):

    if not __showOutdated__:
        writeLog("SerienPlaner: Show only upcoming events", level=xbmc.LOGDEBUG)

    blobs = WINDOW.getProperty('SP.%s.blobs' % category)
    if blobs == '': return 0

    widget = 1
    for i in range(1, int(blobs) + 1, 1):
        if widget > __maxHLCat__ or offset + widget > 16:
            writeLog('Max. Limit of widgets reached, abort processing', level=xbmc.LOGDEBUG)
            break

        writeLog('Processing blob SP.%s.%s for widget #%s' % (category, i, offset + widget), level=xbmc.LOGDEBUG)

        blob = eval(WINDOW.getProperty('SP.%s.%s' % (category, i)))

        if not __showOutdated__:
            _now = datetime.datetime.now()
            try:
                _dt = '%s.%s.%s %s' % (_now.day, _now.month, _now.year, blob['starttime'])
                timestamp = date2timeStamp(_dt, '%d.%m.%Y %H:%M')
                if timestamp + 60 * int(blob['runtime']) < int(time.time()) :
                    writeLog('SerienPlaner: discard blob SP.%s.%s, broadcast @%s has already finished' % (category, i, _dt), level=xbmc.LOGDEBUG)
                    continue
            except ValueError:
                writeLog('Could not determine any date value, discard blob SP.%s.%s' % (category, i), level=xbmc.LOGERROR)
                continue

        WINDOW.setProperty('SerienPlaner.%s.ID' % (offset + widget), blob['id'])
        WINDOW.setProperty('SerienPlaner.%s.TVShow' % (offset + widget), blob['tvshow'])
        WINDOW.setProperty('SerienPlaner.%s.Staffel' % (offset + widget), blob['staffel'])
        WINDOW.setProperty('SerienPlaner.%s.Episode' % (offset + widget), blob['episode'])
        WINDOW.setProperty('SerienPlaner.%s.Title' % (offset + widget), blob['title'])
        WINDOW.setProperty('SerienPlaner.%s.Starttime' % (offset + widget), blob['starttime'])
        WINDOW.setProperty('SerienPlaner.%s.Datum' % (offset + widget), blob['date'])
        WINDOW.setProperty('SerienPlaner.%s.neueEpisode' % (offset + widget), blob['neueepisode'])
        WINDOW.setProperty('SerienPlaner.%s.Channel' % (offset + widget), blob['pvrchannel'])
        WINDOW.setProperty('SerienPlaner.%s.Logo' % (offset + widget), blob['logo'])
        WINDOW.setProperty('SerienPlaner.%s.PVRID' % (offset + widget), blob['pvrid'])
        WINDOW.setProperty('SerienPlaner.%s.Description' % (offset + widget), blob['description'])
        WINDOW.setProperty('SerienPlaner.%s.Rating' % (offset + widget), blob['rating'])
        WINDOW.setProperty('SerienPlaner.%s.Altersfreigabe' % (offset + widget), blob['content_rating'])
        WINDOW.setProperty('SerienPlaner.%s.Genre' % (offset + widget), blob['genre'])
        WINDOW.setProperty('SerienPlaner.%s.Studio' % (offset + widget), blob['studio'])
        WINDOW.setProperty('SerienPlaner.%s.Jahr' % (offset + widget), blob['year'])
        WINDOW.setProperty('SerienPlaner.%s.Thumb' % (offset + widget), blob['thumb'])
        WINDOW.setProperty('SerienPlaner.%s.FirstAired' % (offset + widget), blob['firstaired'])
        WINDOW.setProperty('SerienPlaner.%s.RunningTime' % (offset + widget), blob['runtime'])
        WINDOW.setProperty('SerienPlaner.%s.Poster' % (offset + widget), blob['poster'])        
        WINDOW.setProperty('SerienPlaner.%s.WatchType' % (offset + widget), SPTranslations[blob['category']])
        widget += 1

    return widget - 1

def refreshSerienPlaner():

    offset = 0
    for category in categories():
        offset += refreshWidget(category, offset)
    clearWidgets(offset + 1)

def searchBlob(item, value):

    for category in SPWatchtypes:
        blobs = WINDOW.getProperty('SP.%s.blobs' % category)
        if blobs == '':
            writeLog('No blobs for cat %s' % (category), level=xbmc.LOGDEBUG)
            continue

        for idx in range(1, int(blobs) + 1, 1):
            blob = eval(WINDOW.getProperty('SP.%s.%s' % (category, idx)))
            if blob[item] == value.decode('utf-8'):
                writeLog('Found value \'%s\' in item \'%s\' of blob \'SP.%s.%s\'' % (value.decode('utf-8'), item, category, idx), level=xbmc.LOGDEBUG)
                return blob
    return False

def scrapeWLPage(category):
    url = url = '%s%s/0' % (WLURL, SPWatchtypes[category])
    writeLog('Start scraping category %s from %s' % (category, url), level=xbmc.LOGDEBUG)

    content = getUnicodePage(url, container='<li id="e_')
    i = 1
    content.pop(0)

    blobs = WINDOW.getProperty('SP.%s.blobs' % (category))
    if blobs != '':

        for idx in range(1, int(blobs) + 1, 1):
            WINDOW.clearProperty('SP.%s.%s' % (category, idx))

    for container in content:

        data = WLScraper()
        data.scrapeserien(container)

        pvrchannelID = channelName2channelId(data.channel)
        if not  pvrchannelID:
            writeLog("SerienPlaner: Channel %s is not in PVR, discard entry" % (data.channel), level=xbmc.LOGDEBUG)
            continue   
        if __firstaired__:
            if  "NEU" not in data.neueepisode:
                writeLog("SerienPlaner: TVShow %s %sx%s is not firstaired, discard entry" % (data.tvshowname, data.staffel, data.episode), level=xbmc.LOGDEBUG)
                continue
        logoURL = pvrchannelid2logo(pvrchannelID)
        channel = pvrchannelid2channelname(pvrchannelID)
        if __series_in_db__:
                if not TVShowName2TVShowID(data.tvshowname):
                  writeLog("SerienPlaner: TVShow %s is not in DB, discard entry" % (data.tvshowname), level=xbmc.LOGDEBUG)
                  continue  
        detailURL = 'http://www.wunschliste.de%s' % (data.detailURL)
        seriesUrl = 'http://www.wunschliste.de%s' % (data.nameURL)
        imdbnumber = get_thetvdbID(data.tvshowname)
        if not imdbnumber:
            org_ser_name = WLScraper ()
            org_ser_name.get_original_series_name(getUnicodePage(seriesUrl), data.tvshowname)
            imdbnumber = get_thetvdbID(org_ser_name.orig_tvshow)
            writeLog("SerienPlaner: TVShow has original name: %s" % (imdbnumber), level=xbmc.LOGDEBUG) 
        else:
            pass
        if not imdbnumber:
            writeLog("SerienPlaner: TVShow %s is not in DB, discard entry" % (data.tvshowname), level=xbmc.LOGDEBUG)
            details = WLScraper()
            details.scrapeDetailPage(getUnicodePage(detailURL), 'div class="text"') 
        else:
            details = WLScraper ()
            details.get_detail_thetvdb(imdbnumber, data.staffel, data.episode)

        thumbpath = details.pic_path
        if not thumbpath:
            pic_path = WLScraper ()
            pic_path.get_scrapedetail_pcpath(getUnicodePage(detailURL), 'div class="text"')
            thumbpath = pic_path.pic_path



        writeLog('', level=xbmc.LOGDEBUG)
        writeLog('ID:              SP.%s.%s' %(category, i), level=xbmc.LOGDEBUG)
        writeLog('TVShow:           %s' % (data.tvshowname), level=xbmc.LOGDEBUG)
        writeLog('Staffel:         %s' % (data.staffel), level=xbmc.LOGDEBUG)
        writeLog('Episode:         %s' % (data.episode), level=xbmc.LOGDEBUG)
        writeLog('Title:           %s' % (data.title), level=xbmc.LOGDEBUG)
        writeLog('Starttime:       %s' % (data.tvshowstarttime), level=xbmc.LOGDEBUG)
        writeLog('Datum:           %s' % (data.date), level=xbmc.LOGDEBUG)
        writeLog('neueEpisode:     %s' % (data.neueepisode), level=xbmc.LOGDEBUG)
        writeLog('Channel (SP):    %s' % (data.channel), level=xbmc.LOGDEBUG)
        writeLog('Channel (PVR):   %s' % (channel), level=xbmc.LOGDEBUG)
        writeLog('Channel logo:    %s' % (logoURL), level=xbmc.LOGDEBUG)
        writeLog('ChannelID (PVR): %s' % (pvrchannelID), level=xbmc.LOGDEBUG)
        writeLog('Description:     %s' % (details.plot), level=xbmc.LOGDEBUG)
        writeLog('Rating:          %s' % (details.rating), level=xbmc.LOGDEBUG)
        writeLog('Altersfreigabe:  %s' % (details.content_rating), level=xbmc.LOGDEBUG)
        writeLog('Genre:           %s' % (details.genre), level=xbmc.LOGDEBUG)
        writeLog('Studio:          %s' % (details.studio), level=xbmc.LOGDEBUG)
        writeLog('Status:          %s' % (details.status), level=xbmc.LOGDEBUG)
        writeLog('Jahr:            %s' % (details.year), level=xbmc.LOGDEBUG)
        writeLog('Thumb:           %s' % (thumbpath), level=xbmc.LOGDEBUG)
        writeLog('FirstAired:      %s' % (details.firstaired), level=xbmc.LOGDEBUG)
        writeLog('RunningTime:     %s' % (data.runtime), level=xbmc.LOGDEBUG)
        writeLog('Popup:           %s' % (detailURL), level=xbmc.LOGDEBUG)
        writeLog('poster:          %s' % (details.posterUrl), level=xbmc.LOGDEBUG)
        writeLog('Watchtype:       %s' % (category), level=xbmc.LOGDEBUG)
        writeLog('', level=xbmc.LOGDEBUG)

        blob = {
                'id': unicode('SP.%s.%s' % (i, category)),
                'tvshow': unicode(data.tvshowname),
                'staffel': unicode(data.staffel),
                'episode': unicode(data.episode),
                'title': unicode(data.title),
                'starttime': unicode(data.tvshowstarttime),
                'date': unicode(data.date),
                'neueepisode': unicode(data.neueepisode),
                'channel': unicode(data.channel),                
                'pvrchannel': unicode(channel),
                'logo': unicode(logoURL),
                'pvrid': unicode(pvrchannelID),
                'description': unicode(details.plot),
                'rating': unicode(details.rating),
                'content_rating': unicode(details.content_rating),
                'genre': unicode(details.genre),
                'studio': unicode(details.studio),
                'status': unicode(details.status),
                'year': unicode(details.year),
                'thumb': unicode(thumbpath),
                'firstaired': unicode(details.firstaired),
                'runtime': unicode(data.runtime),
                'poster': unicode(details.posterUrl),
                'category': unicode(category),
               }

        WINDOW.setProperty('SP.%s.%s' % (category, i), str(blob))
        i += 1

    WINDOW.setProperty('SP.%s.blobs' % (category), str(i - 1))


# M A I N
#________

# Get starting methode

methode = None
detailurl = None
pvrid = None

if len(sys.argv)>1:
    params = parameters_string_to_dict(sys.argv[1])
    methode = urllib.unquote_plus(params.get('methode', ''))
    detailurl = urllib.unquote_plus(params.get('detailurl', ''))
    pvrid = urllib.unquote_plus(params.get('pvrid', ''))

writeLog("Methode from external script: %s" % (methode), level=xbmc.LOGDEBUG)
writeLog("Detailurl from external script: %s" % (detailurl), level=xbmc.LOGDEBUG)
writeLog("pvrid from external script: %s" % (pvrid), level=xbmc.LOGDEBUG)

if methode == 'scrape_serien':
    for category in categories():
        scrapeWLPage(category)
    refreshSerienPlaner()

elif methode == 'refresh_screen':
    refreshSerienPlaner()

elif methode == 'switch_channel':
    switchToChannel(int(pvrid))

elif methode=='show_select_dialog':
    writeLog('Methode: show select dialog', level=xbmc.LOGDEBUG)
    dialog = xbmcgui.Dialog()
    cats = [__LS__(30120), __LS__(30121), __LS__(30122), __LS__(30123), __LS__(30116)]
    ret = dialog.select(__LS__(30011), cats)

    if ret == 6:
        refreshHighlights()
    elif 0 <= ret <= 5:
        writeLog('%s selected' % (cats[ret]), level=xbmc.LOGDEBUG)
        scrapeWLPage(SPTranslations1[cats[ret]])
        empty_widgets = refreshWidget(SPTranslations1[cats[ret]])
        clearWidgets(empty_widgets + 1)
    else:
        pass
