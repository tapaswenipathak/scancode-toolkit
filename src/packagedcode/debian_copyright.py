#
# Copyright (c) nexB Inc. and others. All rights reserved.
# http://nexb.com and https://github.com/nexB/scancode-toolkit/
# The ScanCode software is licensed under the Apache License version 2.0.
# Data generated with ScanCode require an acknowledgment.
# ScanCode is a trademark of nexB Inc.
#
# You may not use this software except in compliance with the License.
# You may obtain a copy of the License at: http://apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software distributed
# under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
# CONDITIONS OF ANY KIND, either express or implied. See the License for the
# specific language governing permissions and limitations under the License.
#
# When you publish or redistribute any data created with ScanCode or any ScanCode
# derivative work, you must accompany this data with the following acknowledgment:
#
#  Generated with ScanCode and provided on an "AS IS" BASIS, WITHOUT WARRANTIES
#  OR CONDITIONS OF ANY KIND, either express or implied. No content created from
#  ScanCode should be considered or used as legal advice. Consult an Attorney
#  for any legal advice.
#  ScanCode is a free software code scanning tool from nexB Inc. and others.
#  Visit https://github.com/nexB/scancode-toolkit/ for support and download.

from __future__ import absolute_import
from __future__ import print_function
from __future__ import unicode_literals

import io
import logging
from os import path

from debut.copyright import DebianCopyright
from debut.copyright import CatchAllParagraph
from debut.copyright import CopyrightFilesParagraph
from debut.copyright import CopyrightHeaderParagraph
from license_expression import Licensing

from packagedcode.debian import DebianPackage
from packagedcode.models import compute_normalized_license
from packagedcode.licensing import get_normalized_expression

"""
Detect licenses in Debian copyright files. Can handle dep-5 machine-readable
copyright files, pre-dep-5 mostly machine-readable copyright files and
unstructured copyright files.
"""

TRACE = False

logger = logging.getLogger(__name__)

if TRACE:
    import sys
    logging.basicConfig(level=logging.DEBUG, stream=sys.stdout)
    logger.setLevel(logging.DEBUG)


def get_and_set_package_licenses_and_copyrights(package, root_dir):
    """
    Return a tuple of (declared license, license_expression, copyrights) strings computed
    from the DebianPackage `package` installed in the `root_dir` root directory.
    The package is also updated in place with declared license and license_expression

    For each copyright file paragraph we treat the "name" as a license declaration.
    The text is used for detection and cross-reference with the declaration.
    """
    assert isinstance(package, DebianPackage)
    copyright_file = package.get_copyright_file_path(root_dir)

    results = parse_copyright_file(copyright_file)
    declared_license, detected_license, copyrights = results

    package.license_expression = detected_license
    package.declared_license = declared_license
    package.copyright = copyrights

    return declared_license, detected_license, copyrights


def parse_copyright_file(copyright_file, skip_debian_packaging=True, simplify_licenses=True):
    """
    Return a tuple of (declared license, detected license_expression, copyrights) strings computed
    from the `copyright_file` location. For each copyright file paragraph we
    treat the "name" as a license declaration. The text is used for detection
    and cross-reference with the declaration.
    """
    deco = DebianCopyright.from_file(copyright_file)

    declared_licenses = []
    detected_licenses = []
    copyrights = []

    deco = fix_copyright(deco)

    licensing = Licensing()
    for paragraph in deco.paragraphs:

        if skip_debian_packaging and is_debian_packaging(paragraph):
            # Skipping packaging license and copyrights since they are not
            # relevant to the effective package license
            continue

        if isinstance(paragraph, (CopyrightHeaderParagraph, CopyrightFilesParagraph)):
            pcs = paragraph.copyright.statements or []
            # avoid repeats
            for p in pcs:
                p = p.dumps()
                if p not in copyrights:
                    copyrights.append(p)

        if isinstance(paragraph, CatchAllParagraph):
            text = paragraph.dumps()
            if text:
                detected = get_normalized_expression(text, try_as_expression=False)
                if not detected:
                    detected = 'unknown'
                detected_licenses.append(detected)
        else:
            plicense = paragraph.license
            if not plicense:
                continue

            declared, detected = detect_declared_license(plicense.name)
            # avoid repeats
            if declared and declared not in declared_licenses:
                declared_licenses.append(declared)
            if detected and detected not in detected_licenses:
                detected_licenses.append(detected)

            # also detect in text
            text = paragraph.license.text
            if text:
                detected = get_normalized_expression(text, try_as_expression=False)
                if not detected:
                    detected = 'unknown'
                if detected not in detected_licenses:
                    detected_licenses.append(detected)

    declared_license = '\n'.join(declared_licenses)

    if detected_licenses:
        detected_licenses = [licensing.parse(dl, simple=True) for dl in detected_licenses]

        if len(detected_licenses) > 1:
            detected_license = licensing.AND(*detected_licenses)
        else:
            detected_license = detected_licenses[0]

        if simplify_licenses:
            detected_license = detected_license.simplify()

        detected_license = str(detected_license)

    else:
        detected_license = 'unknown'

    copyrights = '\n'.join(copyrights)
    return declared_license, detected_license, copyrights


def detect_declared_license(declared):
    """
    Return a tuple of (declared license, detected license expression) from a declared license.
    Both can be None.
    """
    # there are few odd cases of license fileds starting with a colon
    declared = declared and declared.strip(': \t')
    if not declared:
        return None, None

    # apply multiple license detection in sequence
    detected = detect_using_name_mapping(declared)
    if detected:
        return declared, detected

    detected = compute_normalized_license(declared)
    return declared, detected


def detect_using_name_mapping(declared):
    """
    Return a license expression detected from a declared_license.
    """
    declared_low = declared.lower()
    detected = get_declared_to_detected().get(declared_low)
    if detected:
        licensing = Licensing()
        return str(licensing.parse(detected, simple=True))


def is_debian_packaging(paragraph):
    """
    Return True if the `paragraph` is a CopyrightFilesParagraph that applies
    only to the Debian packaging
    """
    return (
        isinstance(paragraph, CopyrightFilesParagraph)
        and paragraph.files == 'debian/*'
    )


def fix_copyright(debian_copyright):
    """
    Update in place the `debian_copyright` DebianCopyright object based on
    issues found in a large collection of Debian copyrights such as names that
    rea either copyright staments or license texts.
    """
    for paragraph in debian_copyright.paragraphs:
        if not hasattr(paragraph, 'license'):
            continue

        if not paragraph.license:
            continue

        license_name = paragraph.license.name
        if not license_name:
            continue

        if license_name.startswith('200'):
            # 2005 Sergio Costas
            # 2006-2010 by The HDF Group.

            if isinstance(paragraph, (CopyrightHeaderParagraph, CopyrightFilesParagraph)):
                pcs = paragraph.copyright.statements or []
                pcs.append(license_name)
                paragraph.copyright.statements = pcs
                paragraph.license.name = None

        license_name_low = license_name.lower()
        NOT_A_LICENSE_NAME = (
            'according to',
            'by obtaining',
            'distributed under the terms of the gnu',
            'gnu general public license version 2 as published by the free',
            'gnu lesser general public license 2.1 as published by the',
        )
        if license_name_low.startswith(NOT_A_LICENSE_NAME):
            text = license.text
            if text:
                text = '\n'.join([license_name, text])
            else:
                text = license_name
            license.name = None
            license.text = text

    return debian_copyright


_DECLARED_TO_DETECTED = None


def get_declared_to_detected(data_file=None):
    """
    Return a mapping of declared to detected license expression cached and
    loaded from a tab-separated text file, all lowercase.

    This data file is about license keys used in copyright files and has been
    derived from a large collection of most copyright files from Debian (about
    320K files from circa 2019-11) and Ubuntu (about 200K files from circa
    202-06)
    """
    global _DECLARED_TO_DETECTED
    if _DECLARED_TO_DETECTED:
        return _DECLARED_TO_DETECTED

    _DECLARED_TO_DETECTED = {}
    if not data_file:
        data_file = path.join(path.dirname(__file__), 'debian_licenses.txt')
    with io.open(data_file, encoding='utf-8') as df:
        for line in df:
            decl, _, detect = line.strip().partition('\t')
            if detect and detect.strip():
                decl = decl.strip()
                _DECLARED_TO_DETECTED[decl] = detect
    return _DECLARED_TO_DETECTED
