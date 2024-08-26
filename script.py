import os
import re
import sys
import multiprocessing
import urllib.request
from bs4 import BeautifulSoup


def chomikuj_path_to_utf(path):
    """
    Converts the given Chomikuj path into a UTF-8 string.
    Special characters are translated to their respective UTF-8 encoded values.
    """
    cnum = 0
    out = ''
    while cnum < len(path):
        if path[cnum] == '+':
            out += '%02x' % ord(' ')
        elif path[cnum] == ':':
            out += '%02x' % ord('-')
        elif path[cnum] == '?':
            out += '%02x' % ord('_')
        elif path[cnum] == '*':
            out += path[cnum + 1:cnum + 3]
            cnum += 2
        else:
            out += '%02x' % ord(path[cnum])
        cnum += 1
    return bytes.fromhex(out).decode('utf-8')


class ChomikujMp3Downloader(multiprocessing.Process):
    def __init__(self, fq):
        """
        Initialize the downloader process with a shared queue for tasks.
        """
        super().__init__()
        self.fq = fq

    def run(self):
        """
        The process loop to download files from the shared queue.
        """
        while True:
            d = self.fq.get()
            if d is None:  # Exit signal
                break
            try:
                self.do(d)
            except Exception as e:
                print(f"Error during download: {e}")
            self.fq.task_done()

    def do(self, d):
        """
        Download a single file and save it locally.
        """
        (full_url, local_base, url_base, url_type) = d
        if url_type == 'chomikuj_audio':
            m = re.match(r"^.*/(?P<name>.+),(?P<id>.+)\.(?P<ext>.+)\(audio\)$", full_url)
            if m:
                info = m.groupdict()
                download_url = f'http://chomikuj.pl/Audio.ashx?id={info["id"]}&type=2&tp=mp3'
                name = chomikuj_path_to_utf(info['name']) + '.' + info['ext']
                path = chomikuj_path_to_utf(full_url[len(url_base):])
                path = '/'.join(path.split('/')[:-1])
                dst_dir = os.path.join(local_base, path)
                dst_file = os.path.join(dst_dir, name)

                print(f'Downloading: {name}')
                try:
                    os.makedirs(dst_dir, exist_ok=True)
                except Exception as e:
                    print(f"Error creating directory {dst_dir}: {e}")
                    return

                try:
                    opener = urllib.request.build_opener()
                    opener.addheaders = [('User-agent', 'Mozilla/5.0')]
                    response = opener.open(download_url)
                    file_size = int(response.getheader("Content-Length", 0))
                    data = response.read(file_size)
                    with open(dst_file, 'wb') as dst:
                        dst.write(data)
                    print(f'Downloaded: {name}')
                except Exception as e:
                    print(f"Error downloading file {name}: {e}")


class ChomikujDirectory:
    def __init__(self, url, local, files_queue=None):
        """
        Initialize the directory crawler for Chomikuj with a target URL.
        """
        self.url = url
        self.local = local
        self.fq = files_queue if files_queue is not None else multiprocessing.JoinableQueue()
        self.downloaders_n = 4
        self.download_manager = files_queue is None

    def download(self):
        """
        Start crawling and downloading files from the directory.
        """
        urls_visited = []
        urls_todo = [self.url]
        urls_downloaded = []

        # Start download manager processes if needed
        if self.download_manager:
            downloaders = [ChomikujMp3Downloader(self.fq) for _ in range(self.downloaders_n)]
            for d in downloaders:
                d.start()

        while urls_todo:
            current = urls_todo.pop(0)
            if current in urls_visited:
                continue
            urls_visited.append(current)

            try:
                html = urllib.request.urlopen(current).read()
                soup = BeautifulSoup(html, features="html.parser")
            except Exception as e:
                print(f"Error fetching URL {current}: {e}")
                continue

            # Find and enqueue all audio files for download
            for div in soup.findAll('div', attrs={'id': 'folderContent'}):
                for link in div.findAll('a', attrs={'href': re.compile(r"^.*\(audio\)$")}):
                    full_href = 'http://chomikuj.pl' + link.get('href')
                    if full_href in urls_downloaded:
                        continue
                    urls_downloaded.append(full_href)
                    d = (full_href, self.local, self.url, 'chomikuj_audio')
                    self.fq.put(d)

                # Queue subdirectories for further exploration
                for subdiv in div.findAll('div', attrs={'id': 'foldersList'}):
                    for dir_link in subdiv.findAll('a'):
                        href = 'http://chomikuj.pl' + dir_link.get('href')
                        urls_todo.append(href)

        # Signal download manager processes to exit
        if self.download_manager:
            for _ in range(self.downloaders_n):
                self.fq.put(None)
            self.fq.join()


def main():
    """
    Main function to start the directory crawler and downloader.
    """
    if len(sys.argv) < 2:
        print("Usage: python script.py <chomikuj_directory_url>")
        sys.exit(1)

    url = sys.argv[-1]
    c = ChomikujDirectory(url, '.')
    c.download()


if __name__ == "__main__":
    main()
