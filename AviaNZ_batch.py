# Version 3.0 14/09/20
# Authors: Stephen Marsland, Nirosha Priyadarshani, Julius Juodakis, Virginia Listanti

# This is the processing class for the batch AviaNZ interface

#    AviaNZ bioacoustic analysis program
#    Copyright (C) 2017--2020

#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.

#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
import gc, os, re
import time
import numpy as np

import util.SignalProc as SignalProc
import util.Segment as Segment
import util.WaveletSegment as WaveletSegment
import util.SupportClasses as SupportClasses
import util.wavio as wavio


class AviaNZ_batchProcess:
    # Main class for batch processing
    # Contains the algorithms, not the GUI, so that it can be run from commandline
    def __init__(
        self,
        configdir="",
        recogniser=None,
        maxgap=1.0,
        minlen=0.5,
        maxlen=10.0,
    ):
        # read config and filters from user location
        # recogniser - filter file name without ".txt"
        self.configdir = configdir
        self.configfile = os.path.join(configdir, "AviaNZconfig.txt")
        self.ConfigLoader = SupportClasses.ConfigLoader()
        self.config = self.ConfigLoader.config(self.configfile)

        self.filtersDir = os.path.join(configdir, self.config["FiltersDir"])
        self.FilterDicts = self.ConfigLoader.filters(self.filtersDir)

        # Parameters for "Any sound" post-proc:
        self.maxgap = maxgap
        self.minlen = minlen
        self.maxlen = maxlen

        self.species = [recogniser]

    def detect(self, filename):
        # This is the function that does the work.
        # Chooses the filters and sampling regime to use.
        # Then works through the directory list, and processes each file.

        if "Any sound" in self.species:
            self.method = "Default"
            speciesStr = "Any sound"
            filters = None
        elif "Any sound (Intermittent sampling)" in self.species:
            self.method = "Intermittent sampling"
            speciesStr = "Intermittent sampling"
            filters = None

        self.method = "Wavelets"

        # double-check that all Fs are equal (should already be prevented by UI)
        filters = [self.FilterDicts[name] for name in self.species]
        samplerate = set([filt["SampleRate"] for filt in filters])
        if len(samplerate) > 1:
            raise ValueError(
                "ERROR: multiple sample rates found in selected recognisers, change selection"
            )

        # convert list to string
        speciesStr = " & ".join(self.species)

        # load target CNN models (currently stored in the same dir as filters)
        # format: {filtername: [model, win, inputdim, output]}
        self.CNNDicts = self.ConfigLoader.CNNmodels(
            self.FilterDicts, self.filtersDir, self.species
        )

        allwavs = [filename]

        # Parse the user-set time window to process
        timeWindow_s = 0
        timeWindow_e = 0

        if self.method != "Intermittent sampling":
            settings = [self.method, timeWindow_s, timeWindow_e, False]
        else:
            settings = [
                self.method,
                timeWindow_s,
                timeWindow_e,
                self.config["protocolSize"],
                self.config["protocolInterval"],
            ]

        # Always process all files
        self.filesDone = []

        self.mainloop(allwavs, 1, speciesStr, filters, settings)

        return self.segments

    def mainloop(self, allwavs, total, speciesStr, filters, settings):
        # MAIN PROCESSING starts here
        processingTime = 0
        cleanexit = 0
        cnt = 0

        timeWindow_s = settings[1]
        timeWindow_e = settings[2]

        for filename in allwavs:
            # get remaining run time in min
            processingTimeStart = time.time()
            hh, mm = divmod(processingTime * (total - cnt) / 60, 60)
            cnt = cnt + 1

            # test the selected time window if it is a doc recording
            DOCRecording = re.search(r"(\d{6})_(\d{6})", os.path.basename(filename))
            if DOCRecording:
                startTime = DOCRecording.group(2)
                sTime = (
                    int(startTime[:2]) * 3600
                    + int(startTime[2:4]) * 60
                    + int(startTime[4:6])
                )
                if timeWindow_s == timeWindow_e:
                    # (no time window set)
                    inWindow = True
                elif timeWindow_s < timeWindow_e:
                    # for day times ("8 to 17")
                    inWindow = sTime >= timeWindow_s and sTime <= timeWindow_e
                else:
                    # for times that include midnight ("17 to 8")
                    inWindow = sTime >= timeWindow_s or sTime <= timeWindow_e
            else:
                inWindow = True

            if DOCRecording and not inWindow:
                self.log.appendFile(filename)
                continue

            # ALL SYSTEMS GO: process this file
            self.filename = filename
            self.segments = Segment.SegmentList()

            if self.method == "Intermittent sampling":
                self.addRegularSegments()
            else:
                # load audiodata/spectrogram and clean up old segments:
                # Impulse masking:   TODO masking is useful but could be improved
                if speciesStr == "Any sound":
                    impMask = True  # Up to debate - could turn this off here
                else:
                    # MUST BE off for changepoints (it introduces discontinuities, which
                    # create large WCs and highly distort means/variances)
                    impMask = "chp" not in [sf.get("method") for sf in filters]
                self.loadFile(
                    species=self.species,
                    anysound=(speciesStr == "Any sound"),
                    impMask=impMask,
                )

                # initialize empty segmenter
                if self.method == "Wavelets":
                    self.ws = WaveletSegment.WaveletSegment(wavelet="dmey2")
                    del self.sp
                    gc.collect()

                # Main work is done here:
                self.detectFile(speciesStr, filters)

    def addRegularSegments(self):
        """Perform the Hartley bodge: add 10s segments every minute."""
        # if wav.data exists get the duration
        (_, nseconds, _, _) = wavio.readFmt(self.filename)
        self.segments.metadata = dict()
        self.segments.metadata["Operator"] = "Auto"
        self.segments.metadata["Reviewer"] = ""
        self.segments.metadata["Duration"] = nseconds
        i = 0
        segments = []

        while i < nseconds:
            segments.append([i, i + self.config["protocolSize"]])
            i += self.config["protocolInterval"]
        post = Segment.PostProcess(
            configdir=self.configdir,
            audioData=None,
            sampleRate=0,
            segments=segments,
            subfilter={},
            cert=0,
        )
        self.makeSegments(self.segments, post.segments)

    def detectFile(self, speciesStr, filters):
        """Actual worker for a file in the detection loop.
        Does not return anything - for use with external try/catch
        """
        # Segment over pages separately, to allow dealing with large files smoothly:
        # (page size is shorter for low freq things, i.e. bittern,
        # since those freqs are very noisy and variable)
        if self.sampleRate <= 4000:
            # Basically bittern
            samplesInPage = 300 * self.sampleRate
        elif self.method == "Wavelets":
            # If using changepoints and v short windows,
            # aim to have roughly 5000 windows:
            # (4500 = 4 windows in 15 min DoC standard files)
            winsize = [
                subf["WaveletParams"].get("win", 1)
                for f in filters
                for subf in f["Filters"]
            ]
            winsize = min(winsize)
            if winsize < 0.05:
                samplesInPage = int(4500 * 0.05 * self.sampleRate)
            else:
                samplesInPage = 900 * 16000
        else:
            # A sensible default
            samplesInPage = 900 * 16000

        # (ceil division for large integers)
        numPages = (self.datalength - 1) // samplesInPage + 1

        # Actual segmentation happens here:
        for page in range(numPages):
            start = page * samplesInPage
            end = min(start + samplesInPage, self.datalength)
            thisPageLen = (end - start) / self.sampleRate

            if thisPageLen < 2 and (self.method != "Click" and self.method != "Bats"):
                continue

            # Process
            if speciesStr == "Any sound":
                # Create spectrogram for median clipping etc
                if not hasattr(self, "sp"):
                    self.sp = SignalProc.SignalProc(
                        self.config["window_width"], self.config["incr"]
                    )
                self.sp.data = self.audiodata[start:end]
                self.sp.sampleRate = self.sampleRate
                _ = self.sp.spectrogram(
                    window="Hann", sgType="Standard", mean_normalise=True, onesided=True
                )
                self.seg = Segment.Segmenter(self.sp, self.sampleRate)
                # thisPageSegs = self.seg.bestSegments()
                thisPageSegs = self.seg.medianClip(thr=3.5)
                # Post-process
                post = Segment.PostProcess(
                    configdir=self.configdir,
                    audioData=self.audiodata[start:end],
                    sampleRate=self.sampleRate,
                    segments=thisPageSegs,
                    subfilter={},
                    cert=0,
                )
                post.joinGaps(self.maxgap)
                post.deleteShort(self.minlen)
                # avoid extra long segments (for Isabel)
                post.splitLong(self.maxlen)

                # adjust segment starts for 15min "pages"
                if start != 0:
                    for seg in post.segments:
                        seg[0][0] += start / self.sampleRate
                        seg[0][1] += start / self.sampleRate
                # attach mandatory "Don't Know"s etc and put on self.segments
                self.makeSegments(self.segments, post.segments)
                del self.seg
                gc.collect()
            else:
                if self.method != "Click" and self.method != "Bats":
                    # read in the page and resample as needed
                    self.ws.readBatch(
                        self.audiodata[start:end],
                        self.sampleRate,
                        d=False,
                        spInfo=filters,
                        wpmode="new",
                        wind=False,
                    )

                for speciesix in range(len(filters)):
                    # Bird detection by wavelets. Choose the right wavelet method:
                    if (
                        "method" not in filters[speciesix]
                        or filters[speciesix]["method"] == "wv"
                    ):
                        # note: using 'recaa' mode = partial antialias
                        thisPageSegs = self.ws.waveletSegment(speciesix, wpmode="new")
                    elif filters[speciesix]["method"] == "chp":
                        # note that only allowing alg2 = nuisance-robust chp detection
                        thisPageSegs = self.ws.waveletSegmentChp(
                            speciesix, alg=2, wind=False
                        )
                    else:
                        print(
                            "ERROR: unrecognized method", filters[speciesix]["method"]
                        )
                        raise Exception

                    # Post-process:
                    # CNN-classify, delete windy, rainy segments, check for FundFreq, merge gaps etc.
                    # postProcess currently operates on single-level list of segments,
                    # so we run it over subfilters for wavelets:
                    spInfo = filters[speciesix]
                    for filtix in range(len(spInfo["Filters"])):
                        CNNmodel = None
                        if "CNN" in spInfo:
                            if spInfo["CNN"]["CNN_name"] in self.CNNDicts.keys():
                                # This list contains the model itself, plus parameters for running it
                                CNNmodel = self.CNNDicts[spInfo["CNN"]["CNN_name"]]

                        # TODO THIS IS FULL POST-PROC PIPELINE FOR BIRDS AND BATS
                        # -- Need to check how this should interact with the testmode
                        # bird-style CNN and other processing:
                        postsegs = self.postProcFull(
                            thisPageSegs, spInfo, filtix, start, end, CNNmodel
                        )
                        # attach filter info and put on self.segments:
                        self.makeSegments(
                            self.segments,
                            postsegs,
                            self.species[speciesix],
                            spInfo["species"],
                            spInfo["Filters"][filtix],
                        )
        return len(postsegs)

    def postProcFull(self, segments, spInfo, filtix, start, end, CNNmodel):
        """Full bird-style postprocessing (CNN, joinGaps...)
        segments: list of segments over calltypes
        start, end: start and end of this page, in samples
        CNNmodel: None or a CNN
        """
        subfilter = spInfo["Filters"][filtix]
        post = Segment.PostProcess(
            configdir=self.configdir,
            audioData=self.audiodata[start:end],
            sampleRate=self.sampleRate,
            tgtsampleRate=spInfo["SampleRate"],
            segments=segments[filtix],
            subfilter=subfilter,
            CNNmodel=CNNmodel,
            cert=50,
        )

        if CNNmodel:
            post.CNN()

        # Fund freq and merging. Only do for standard wavelet filter currently:
        # (for median clipping, gap joining and some short segment cleanup was already done in WaveletSegment)
        if "method" not in spInfo or spInfo["method"] == "wv":
            if "F0" in subfilter and "F0Range" in subfilter and subfilter["F0"]:
                post.fundamentalFrq()

            post.joinGaps(maxgap=subfilter["TimeRange"][3])

        # delete short segments, if requested:
        if subfilter["TimeRange"][0] > 0:
            post.deleteShort(minlength=subfilter["TimeRange"][0])

        # adjust segment starts for 15min "pages"
        if start != 0:
            for seg in post.segments:
                seg[0][0] += start / self.sampleRate
                seg[0][1] += start / self.sampleRate
        return post.segments

    def makeSegments(
        self, segmentsList, segmentsNew, filtName=None, species=None, subfilter=None
    ):
        """Adds segmentsNew to segmentsList"""
        if subfilter is not None:
            y1 = subfilter["FreqRange"][0]
            y2 = min(subfilter["FreqRange"][1], self.sampleRate // 2)
            for s in segmentsNew:
                segment = Segment.Segment(
                    [
                        s[0][0],
                        s[0][1],
                        y1,
                        y2,
                        [
                            {
                                "species": species,
                                "certainty": s[1],
                                "filter": filtName,
                                "calltype": subfilter["calltype"],
                            }
                        ],
                    ]
                )
                segmentsList.addSegment(segment)
        else:
            # for generic all-species segments:
            y1 = 0
            y2 = 0
            species = "Don't Know"
            cert = 0.0
            segmentsList.addBasicSegments(
                segmentsNew, [y1, y2], species=species, certainty=cert
            )

    def saveAnnotation(self, segmentList, suffix=".data"):
        """Generates default batch-mode metadata,
        and saves the segmentList to a .data file.
        suffix arg can be used to export .tmpdata during testing.
        """
        if not hasattr(segmentList, "metadata"):
            segmentList.metadata = dict()
        segmentList.metadata["Operator"] = "Auto"
        segmentList.metadata["Reviewer"] = ""
        if self.method != "Intermittent sampling":
            segmentList.metadata["Duration"] = float(self.datalength) / self.sampleRate
        segmentList.metadata["noiseLevel"] = None
        segmentList.metadata["noiseTypes"] = []

        segmentList.saveJSON(str(self.filename) + suffix)
        return 1

    def loadFile(self, species, anysound=False, impMask=True):
        """species: list of recognizer names, or ["Any sound"].
        Species names will be wiped based on these."""
        # Create an instance of the Signal Processing class
        if not hasattr(self, "sp"):
            self.sp = SignalProc.SignalProc(
                self.config["window_width"], self.config["incr"]
            )

        # Read audiodata or spectrogram
        self.sp.readWav(self.filename)
        self.sampleRate = self.sp.sampleRate
        self.audiodata = self.sp.data

        self.datalength = np.shape(self.audiodata)[0]

        # Read in stored segments (useful when doing multi-species)
        self.segments = Segment.SegmentList()
        if (
            species == ["Any sound"]
            or not os.path.isfile(self.filename + ".data")
            or self.method == "Click"
            or self.method == "Bats"
        ):
            # Initialize default metadata values
            self.segments.metadata = dict()
            self.segments.metadata["Operator"] = "Auto"
            self.segments.metadata["Reviewer"] = ""
            self.segments.metadata["Duration"] = (
                float(self.datalength) / self.sampleRate
            )
            # wipe all segments:
            self.segments.clear()
        else:
            self.segments.parseJSON(
                self.filename + ".data", float(self.datalength) / self.sampleRate
            )
            # wipe same species:
            for sp in species:
                # shorthand for double-checking that it's not "Any Sound" etc
                if sp in self.FilterDicts:
                    spname = self.FilterDicts[sp]["species"]
                    oldsegs = self.segments.getSpecies(spname)
                    for i in reversed(oldsegs):
                        wipeAll = self.segments[i].wipeSpecies(spname)
                        if wipeAll:
                            del self.segments[i]

        # impulse masking (on by default)
        if impMask:
            if anysound:
                self.sp.data = self.sp.impMask(engp=70, fp=0.50)
            else:
                self.sp.data = self.sp.impMask()
            self.audiodata = self.sp.data

    def updateDataset(
        self, file_name, featuress, count, spectrogram, click_start, click_end, dt=None
    ):
        """
        Update Dataset with current segment
        It take a piece of the spectrogram with fixed length centered in the click
        """
        win_pixel = 1
        ls = np.shape(spectrogram)[1] - 1
        click_center = int((click_start + click_end) / 2)

        start_pixel = click_center - win_pixel
        if start_pixel < 0:
            win_pixel2 = win_pixel + np.abs(start_pixel)
            start_pixel = 0
        else:
            win_pixel2 = win_pixel

        end_pixel = click_center + win_pixel2
        if end_pixel > ls:
            start_pixel -= end_pixel - ls + 1
            end_pixel = ls - 1
            # this code above fails for sg less than 4 pixels wide
        sgRaw = spectrogram[
            :, start_pixel : end_pixel + 1
        ]  # not I am saving the spectrogram in the right dimension
        sgRaw = np.repeat(sgRaw, 2, axis=1)
        sgRaw = (
            np.flipud(sgRaw)
        ).T  # flipped spectrogram to make it consistent with Niro Mewthod
        featuress.append(
            [sgRaw.tolist(), file_name, count]
        )  # not storing segment and label informations

        count += 1

        return featuress, count
