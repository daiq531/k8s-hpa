<?php
    $started = microtime(true);
    // CPU stress test
    for($i = 0; $i < 300000; $i++) {
        $a = sqrt($i);
    }
    $ended = microtime(true);
    if (!empty($_GET['print'])) {
        echo '       Php: ' . PHP_VERSION ."\n";
    //    echo '   Started: ' . $started ."\n";
    //    echo '     Ended: ' . $ended ."\n";
        echo 'Total Time: ' . round( $ended - $started, 4)."\n";
    }
?>
